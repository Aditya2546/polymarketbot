# Kalshi API Setup Guide

## Overview

Kalshi uses **RSA key-based authentication** for API access. This is more secure than password-based authentication and is the standard for financial trading APIs.

## Step-by-Step Setup

### 1. Create Kalshi Account

If you don't have one already:
1. Go to https://kalshi.com
2. Sign up for an account
3. Complete identity verification (required for trading)
4. Deposit funds if you plan to trade

### 2. Generate API Credentials

1. Log into your Kalshi account
2. Navigate to **Account → API Settings**: https://kalshi.com/account/api
3. Click **"Generate API Key"** or **"Create New Key"**
4. Kalshi will:
   - Generate an **API Key ID** (looks like: `a1b2c3d4-e5f6-7890-abcd-ef1234567890`)
   - Generate an **RSA key pair** (public + private keys)
   - Show you the Key ID on screen
   - **Download the private key file** (usually named something like `kalshi_private_key.pem`)

**CRITICAL**: 
- Save the private key file immediately - you cannot download it again!
- Store it securely - anyone with this file can trade on your account!
- The Key ID is shown on the Kalshi website and can be copied anytime

### 3. Secure Your Private Key

```bash
# Create a secure directory for keys (if it doesn't exist)
mkdir -p ~/.kalshi

# Move your downloaded private key there
mv ~/Downloads/kalshi_private_key.pem ~/.kalshi/

# Set secure permissions (only you can read)
chmod 600 ~/.kalshi/kalshi_private_key.pem
```

### 4. Configure the Bot

Edit `config.yaml`:

```yaml
kalshi:
  api_key_id: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"  # Your Key ID from Kalshi
  private_key_path: "/Users/yourname/.kalshi/kalshi_private_key.pem"  # Path to private key
  base_url: "https://api.elections.kalshi.com/trade-api/v2"
  ws_url: "wss://api.elections.kalshi.com/trade-api/ws/v2"
```

**Important**: Use the **full absolute path** to your private key file.

### 5. Verify Setup

Test that authentication works:

```bash
source venv/bin/activate
python -c "
from src.config import get_config
from src.data.kalshi_client import KalshiClient
import asyncio

async def test():
    config = get_config()
    client = KalshiClient(
        api_key_id=config.kalshi_api_key_id,
        private_key_path=config.kalshi_private_key_path
    )
    await client.start()
    balance = await client.get_balance()
    print(f'✓ Authentication successful! Balance: ${balance}')
    await client.stop()

asyncio.run(test())
"
```

If you see your balance, authentication is working!

## Troubleshooting

### Error: "Failed to load private key"

**Cause**: Private key file not found or wrong path

**Solution**:
```bash
# Check if file exists
ls -la ~/.kalshi/kalshi_private_key.pem

# Verify path in config.yaml matches
cat config.yaml | grep private_key_path

# Make sure you're using absolute path, not relative
# Good: /Users/yourname/.kalshi/kalshi_private_key.pem
# Bad:  ./kalshi_private_key.pem
```

### Error: "Authentication failed (status 401)"

**Causes**:
1. Wrong API Key ID
2. Private key doesn't match the Key ID
3. API key has been revoked/deleted

**Solutions**:
1. Double-check Key ID from Kalshi website
2. Make sure you're using the private key that was downloaded with that Key ID
3. Generate a new API key on Kalshi if the old one was deleted

### Error: "Authentication failed (status 403)"

**Cause**: API key doesn't have required permissions

**Solution**:
1. Go to Kalshi API settings
2. Check key permissions
3. Enable required permissions (trading, market data, etc.)
4. Or generate a new key with all permissions

### Error: "Permission denied" when reading private key

**Cause**: File permissions too restrictive or too open

**Solution**:
```bash
# Set correct permissions
chmod 600 ~/.kalshi/kalshi_private_key.pem

# Verify ownership
ls -la ~/.kalshi/kalshi_private_key.pem
# Should show: -rw------- 1 yourname yourgroup
```

## Security Best Practices

### ✅ DO:
- Store private key file outside of project directory
- Use `chmod 600` to restrict file permissions
- Add `*.pem` to `.gitignore`
- Use environment variables for key path in production
- Rotate API keys periodically
- Use different API keys for development vs production

### ❌ DON'T:
- Commit private key files to git
- Share private key files
- Use same API key across multiple machines
- Store private key in cloud storage (Dropbox, Google Drive, etc.)
- Email private key files
- Use production API keys for testing

## Alternative: Environment Variables

Instead of putting paths in `config.yaml`, you can use environment variables:

```bash
# Add to ~/.bashrc or ~/.zshrc
export KALSHI_API_KEY_ID="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
export KALSHI_PRIVATE_KEY_PATH="/Users/yourname/.kalshi/kalshi_private_key.pem"
```

Then config.yaml can be left with placeholders:

```yaml
kalshi:
  api_key_id: "YOUR_KALSHI_API_KEY_ID"
  private_key_path: "path/to/your/private_key.pem"
```

The bot will automatically use environment variables if set.

## Key Rotation

It's good practice to rotate API keys periodically:

1. Generate new API key on Kalshi
2. Download new private key
3. Update `config.yaml` with new Key ID and path
4. Test that new credentials work
5. Delete old API key on Kalshi website
6. Securely delete old private key file:
   ```bash
   shred -u ~/.kalshi/old_private_key.pem  # Linux
   rm -P ~/.kalshi/old_private_key.pem     # macOS
   ```

## API Rate Limits

Kalshi has rate limits on API requests. Current limits (as of 2026):

- **REST API**: 100 requests per minute per key
- **WebSocket**: 10 connections per key

The bot respects these limits with:
- Request throttling
- Exponential backoff on rate limit errors
- Connection pooling for WebSocket

## References

- **Kalshi API Documentation**: https://docs.kalshi.com
- **API Keys Guide**: https://docs.kalshi.com/getting_started/api_keys
- **Python SDK**: https://docs.kalshi.com/python-sdk
- **API Reference**: https://docs.kalshi.com/api-reference

## Support

If you have issues with API access:

1. Check Kalshi API status: https://status.kalshi.com
2. Review API documentation: https://docs.kalshi.com
3. Contact Kalshi support: support@kalshi.com
4. Check this bot's logs: `logs/main.log`

## Example: Testing Authentication Manually

```python
import asyncio
from src.data.kalshi_client import KalshiClient

async def test_kalshi_auth():
    """Test Kalshi authentication."""
    # Replace with your credentials
    client = KalshiClient(
        api_key_id="YOUR_KEY_ID",
        private_key_path="/path/to/private_key.pem"
    )
    
    try:
        await client.start()
        print("✓ Authentication successful!")
        
        # Test market discovery
        markets = await client.get_markets(status="open")
        print(f"✓ Found {len(markets)} open markets")
        
        # Test balance
        balance = await client.get_balance()
        print(f"✓ Account balance: ${balance}")
        
        await client.stop()
        print("✓ All tests passed!")
        
    except Exception as e:
        print(f"✗ Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_kalshi_auth())
```

Save this as `test_auth.py` and run:
```bash
python test_auth.py
```

---

**You're now ready to use the Kalshi API!** 🚀

Remember: Keep your private key secure, never share it, and never commit it to git.

