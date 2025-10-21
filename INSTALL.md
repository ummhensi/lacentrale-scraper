# Installation Guide

## Prerequisites

- **Python 3.8+** installed on your system
- **Google Chrome** browser
- **Ubuntu VPS** (recommended) or local machine
- **Internet connection**

## Step-by-Step Installation

### 1. Clone the Repository

```bash
# Clone the repository
git clone https://github.com/yourusername/lacentrale-scraper.git
cd lacentrale-scraper
```

### 2. Create Virtual Environment (Recommended)

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Ubuntu/Linux
# or
venv\Scripts\activate     # On Windows
```

### 3. Install Python Dependencies

```bash
# Install required packages
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 4. Setup Chrome for Remote Debugging

**Option A: Manual Chrome Setup**
```bash
# Start Chrome with remote debugging (run this in a separate terminal)
google-chrome --remote-debugging-port=9222 --user-data-dir=~/.chrome-debug
```

**Option B: Create a Startup Script**
```bash
# Create a startup script
cat > start_chrome.sh << 'EOF'
#!/bin/bash
google-chrome --remote-debugging-port=9222 --user-data-dir=~/.chrome-debug --no-first-run --no-default-browser-check
EOF

chmod +x start_chrome.sh
./start_chrome.sh
```

### 5. Test the Installation

```bash
# Run the scraper
python scraper_cdp.py
```

## Troubleshooting Installation

### Common Issues

**"python3: command not found"**
```bash
# Install Python 3
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

**"playwright: command not found"**
```bash
# Install Playwright
pip install playwright
playwright install chromium
```

**"Chrome not found"**
```bash
# Install Google Chrome
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update
sudo apt install google-chrome-stable
```

**"Permission denied" errors**
```bash
# Fix permissions
chmod +x scraper_cdp.py
chmod +x start_chrome.sh
```

### Verification Steps

1. **Check Python version**: `python3 --version` (should be 3.8+)
2. **Check Chrome**: `google-chrome --version`
3. **Check Playwright**: `playwright --version`
4. **Test Chrome debugging**: Visit `http://localhost:9222` in your browser

## Docker Installation (Alternative)

If you prefer Docker:

```bash
# Create Dockerfile
cat > Dockerfile << 'EOF'
FROM python:3.9-slim

# Install Chrome
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN playwright install chromium

# Copy application
COPY . .

# Run the scraper
CMD ["python", "scraper_cdp.py"]
EOF

# Build and run
docker build -t lacentrale-scraper .
docker run -v $(pwd):/app lacentrale-scraper
```

## Next Steps

After successful installation:

1. **Configure the scraper** by editing `scraper_cdp.py`
2. **Start Chrome** with remote debugging
3. **Run the scraper** and follow the prompts
4. **Check output files** (`lacentrale_listings.xlsx` and `lacentrale_listings.json`)

## Getting Help

If you encounter issues:

1. Check the [troubleshooting section](README.md#troubleshooting) in the main README
2. Look at debug files in `./debug_http/`
3. Open an issue on GitHub with your error details
