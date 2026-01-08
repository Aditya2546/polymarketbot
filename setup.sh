#!/bin/bash

# Setup script for Kalshi 15-Minute BTC Direction Assistant

set -e

echo "=================================="
echo "Kalshi BTC Assistant Setup"
echo "=================================="
echo ""

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Found Python $python_version"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo ""
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install -r requirements.txt

# Create necessary directories
echo ""
echo "Creating directories..."
mkdir -p logs
mkdir -p data
mkdir -p debug

# Create config file if it doesn't exist
if [ ! -f "config.yaml" ]; then
    echo ""
    echo "Creating config file from template..."
    cp config.template.yaml config.yaml
    echo ""
    echo "⚠️  IMPORTANT: Edit config.yaml and add your Kalshi API credentials!"
    echo ""
fi

# Run tests
echo ""
echo "Running tests..."
pytest tests/ -v

echo ""
echo "=================================="
echo "Setup complete!"
echo "=================================="
echo ""
echo "Next steps:"
echo "1. Edit config.yaml and add your Kalshi API credentials"
echo "2. Activate virtual environment: source venv/bin/activate"
echo "3. Run live signals: python main.py --mode live"
echo "4. Run paper trading: python main.py --mode paper"
echo ""
echo "For more information, see README.md"
echo ""

