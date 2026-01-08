"""Live console UI using Rich."""

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text

from ..data.kalshi_client import KalshiMarket
from ..models.settlement_engine import SettlementEngine
from ..models.probability_model import ProbabilityModel
from ..models.edge_detector import EdgeDetector
from ..strategy.signal_generator import SignalGenerator, TradeSignal
from ..strategy.risk_manager import RiskManager


class ConsoleUI:
    """Live console UI for trading assistant."""
    
    def __init__(
        self,
        settlement_engine: SettlementEngine,
        probability_model: ProbabilityModel,
        edge_detector: EdgeDetector,
        signal_generator: SignalGenerator,
        risk_manager: RiskManager,
        refresh_rate: float = 2.0,
        compact: bool = False
    ):
        """Initialize console UI.
        
        Args:
            settlement_engine: Settlement engine instance
            probability_model: Probability model instance
            edge_detector: Edge detector instance
            signal_generator: Signal generator instance
            risk_manager: Risk manager instance
            refresh_rate: Display refresh rate (Hz)
            compact: Use compact mode
        """
        self.settlement_engine = settlement_engine
        self.probability_model = probability_model
        self.edge_detector = edge_detector
        self.signal_generator = signal_generator
        self.risk_manager = risk_manager
        self.refresh_rate = refresh_rate
        self.compact = compact
        
        self.console = Console()
        self.live: Optional[Live] = None
        
        # State
        self.current_market: Optional[KalshiMarket] = None
        self.baseline: Optional[float] = None
        self.settle_timestamp: Optional[float] = None
        self.current_signal: Optional[TradeSignal] = None
    
    def update_market(
        self,
        market: KalshiMarket,
        baseline: float,
        settle_timestamp: float
    ) -> None:
        """Update current market info.
        
        Args:
            market: Current market
            baseline: Baseline price
            settle_timestamp: Settlement timestamp
        """
        self.current_market = market
        self.baseline = baseline
        self.settle_timestamp = settle_timestamp
    
    def update_signal(self, signal: Optional[TradeSignal]) -> None:
        """Update current signal.
        
        Args:
            signal: Current signal or None
        """
        self.current_signal = signal
    
    def _create_market_panel(self) -> Panel:
        """Create market info panel.
        
        Returns:
            Panel with market info
        """
        if not self.current_market:
            return Panel("No active market", title="📊 Market Info")
        
        market = self.current_market
        
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")
        
        table.add_row("Market", market.ticker)
        table.add_row("Status", market.status)
        
        if self.baseline:
            table.add_row("Baseline", f"${self.baseline:,.2f}")
        
        if self.settle_timestamp:
            import time
            seconds_left = max(0, self.settle_timestamp - time.time())
            minutes = int(seconds_left // 60)
            seconds = int(seconds_left % 60)
            table.add_row("Time to Settle", f"{minutes}m {seconds}s")
        
        # Prices
        if market.yes_bid is not None and market.yes_ask is not None:
            table.add_row("YES", f"{market.yes_bid:.2f} / {market.yes_ask:.2f}")
        if market.no_bid is not None and market.no_ask is not None:
            table.add_row("NO", f"{market.no_bid:.2f} / {market.no_ask:.2f}")
        
        spread = market.get_spread()
        if spread:
            table.add_row("Spread", f"{spread:.2%}")
        
        return Panel(table, title="📊 Market Info")
    
    def _create_model_panel(self) -> Panel:
        """Create model status panel.
        
        Returns:
            Panel with model status
        """
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")
        
        # Current price
        current_price = self.settlement_engine.brti_feed.get_current_price()
        if current_price:
            table.add_row("Current BTC", f"${current_price:,.2f}")
        
        # Avg60
        avg60_a, avg60_b = self.settlement_engine.get_both_avg60()
        if avg60_a:
            table.add_row("Avg60 (A)", f"${avg60_a:,.2f}")
        if avg60_b:
            table.add_row("Avg60 (B)", f"${avg60_b:,.2f}")
        
        # Distance to threshold
        if self.baseline and avg60_a:
            distance = avg60_a - self.baseline
            color = "green" if distance > 0 else "red"
            table.add_row(
                "Distance",
                f"[{color}]${distance:+,.2f}[/{color}]"
            )
        
        # Probabilities
        p_yes, p_no = self.probability_model.get_probabilities()
        if p_yes is not None:
            table.add_row("P(YES)", f"{p_yes:.4f}")
        if p_no is not None:
            table.add_row("P(NO)", f"{p_no:.4f}")
        
        # Volatility
        if self.probability_model.volatility:
            table.add_row("Volatility", f"{self.probability_model.volatility:.6f}")
        
        return Panel(table, title="🔮 Model Status")
    
    def _create_edge_panel(self) -> Panel:
        """Create edge detection panel.
        
        Returns:
            Panel with edge info
        """
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")
        
        # Edge measurements
        if self.edge_detector.edge_yes:
            edge = self.edge_detector.edge_yes
            color = "green" if edge.edge_net > 0 else "red"
            table.add_row(
                "Edge YES",
                f"[{color}]{edge.edge_net:+.4f}[/{color}]"
            )
        
        if self.edge_detector.edge_no:
            edge = self.edge_detector.edge_no
            color = "green" if edge.edge_net > 0 else "red"
            table.add_row(
                "Edge NO",
                f"[{color}]{edge.edge_net:+.4f}[/{color}]"
            )
        
        # Latency
        latency = self.edge_detector.get_average_latency_ms()
        if latency is not None:
            color = "red" if latency > 200 else "yellow" if latency > 100 else "green"
            table.add_row("Latency", f"[{color}]{latency:.1f}ms[/{color}]")
        
        # Threshold
        threshold = self.edge_detector.get_latency_adjusted_threshold()
        table.add_row("Threshold", f"{threshold:.4f}")
        
        # Signal status
        has_signal = self.edge_detector.has_signal()
        signal_text = "[green]YES[/green]" if has_signal else "[dim]NO[/dim]"
        table.add_row("Has Signal", signal_text)
        
        return Panel(table, title="⚡ Edge Detection")
    
    def _create_signal_panel(self) -> Panel:
        """Create signal panel.
        
        Returns:
            Panel with current signal
        """
        if not self.current_signal:
            return Panel("[dim]No active signal[/dim]", title="🎯 Trade Signal")
        
        signal = self.current_signal
        
        # Create signal display
        lines = []
        
        # Header
        side_color = "green" if signal.side == "YES" else "red"
        lines.append(f"[bold {side_color}]{signal.side} {signal.market_id}[/bold {side_color}]")
        lines.append("")
        
        # Details
        lines.append(f"Type: {signal.signal_type}")
        lines.append(f"Edge: [bold]{signal.edge:+.2%}[/bold]")
        lines.append(f"Size: [bold]${signal.recommended_size_usd:.2f}[/bold]")
        lines.append(f"P(true): {signal.p_true:.4f}")
        lines.append(f"P(market): {signal.p_market:.4f}")
        lines.append("")
        lines.append(f"[italic]{signal.reason}[/italic]")
        
        content = "\n".join(lines)
        
        return Panel(content, title="🎯 Trade Signal", border_style="bold yellow")
    
    def _create_risk_panel(self) -> Panel:
        """Create risk management panel.
        
        Returns:
            Panel with risk metrics
        """
        metrics = self.risk_manager.get_metrics()
        
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")
        
        # Bankroll
        bankroll = metrics["current_bankroll"]
        peak = metrics["peak_bankroll"]
        table.add_row("Bankroll", f"${bankroll:.2f}")
        table.add_row("Peak", f"${peak:.2f}")
        
        # PnL
        daily_pnl = metrics["daily_pnl"]
        pnl_color = "green" if daily_pnl >= 0 else "red"
        table.add_row("Daily P&L", f"[{pnl_color}]${daily_pnl:+.2f}[/{pnl_color}]")
        
        # Drawdown
        drawdown = metrics["drawdown"]
        dd_color = "red" if drawdown > 0.15 else "yellow" if drawdown > 0.10 else "green"
        table.add_row("Drawdown", f"[{dd_color}]{drawdown:.1%}[/{dd_color}]")
        
        # Positions
        table.add_row("Open Positions", str(metrics["num_open"]))
        table.add_row("Open Exposure", f"${metrics['open_exposure']:.2f}")
        table.add_row("Available", f"${metrics['available_budget']:.2f}")
        
        # Performance
        if metrics["num_trades"] > 0:
            table.add_row("Win Rate", f"{metrics['win_rate']:.1%}")
        
        # Status
        if metrics["is_halted"]:
            table.add_row("[red]STATUS[/red]", "[red bold]HALTED[/red bold]")
            if metrics["halt_reason"]:
                table.add_row("Reason", f"[red]{metrics['halt_reason']}[/red]")
        elif metrics["in_cooldown"]:
            table.add_row("STATUS", "[yellow]COOLDOWN[/yellow]")
        else:
            table.add_row("STATUS", "[green]ACTIVE[/green]")
        
        return Panel(table, title="💰 Risk Management")
    
    def _create_layout(self) -> Layout:
        """Create dashboard layout.
        
        Returns:
            Layout object
        """
        layout = Layout()
        
        # Header
        layout.split(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3)
        )
        
        # Header content
        header_text = Text("Kalshi 15-Minute BTC Direction Assistant", style="bold magenta")
        header_text.append(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", style="dim")
        layout["header"].update(Panel(header_text, border_style="magenta"))
        
        # Main area
        if self.compact:
            layout["main"].split_row(
                Layout(name="left"),
                Layout(name="right")
            )
            
            layout["left"].split(
                Layout(self._create_market_panel()),
                Layout(self._create_model_panel())
            )
            
            layout["right"].split(
                Layout(self._create_edge_panel()),
                Layout(self._create_signal_panel())
            )
        else:
            layout["main"].split_row(
                Layout(name="left"),
                Layout(name="middle"),
                Layout(name="right")
            )
            
            layout["left"].split(
                Layout(self._create_market_panel()),
                Layout(self._create_model_panel())
            )
            
            layout["middle"].split(
                Layout(self._create_edge_panel()),
                Layout(self._create_risk_panel())
            )
            
            layout["right"].update(self._create_signal_panel())
        
        # Footer
        footer_text = Text("Press Ctrl+C to exit", style="dim italic", justify="center")
        layout["footer"].update(footer_text)
        
        return layout
    
    async def run(self) -> None:
        """Run live console UI."""
        with Live(
            self._create_layout(),
            console=self.console,
            refresh_per_second=self.refresh_rate,
            screen=True
        ) as live:
            self.live = live
            
            try:
                while True:
                    live.update(self._create_layout())
                    await asyncio.sleep(1 / self.refresh_rate)
            except KeyboardInterrupt:
                pass
            finally:
                self.live = None
    
    def stop(self) -> None:
        """Stop console UI."""
        if self.live:
            self.live.stop()

