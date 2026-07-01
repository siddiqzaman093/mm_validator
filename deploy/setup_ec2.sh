#!/usr/bin/env bash
##
## EC2 Setup Script for SAP MM Validator
## Tested on: Ubuntu 22.04 LTS (t3.small or larger)
##
## Run as ubuntu user AFTER uploading the mm_validator folder to the server:
##   chmod +x setup_ec2.sh && ./setup_ec2.sh
##

set -euo pipefail

APP_DIR="/opt/mmvalidator"
STATIC_DIR="/var/www/mmvalidator"

echo "==> [1/7] Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

echo "==> [2/7] Installing Nginx, Python, Node.js..."
sudo apt-get install -y nginx python3 python3-pip python3-venv

# Install Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

echo "==> [3/7] Setting up backend..."
sudo mkdir -p "$APP_DIR"
sudo cp -r backend/. "$APP_DIR/backend/"
# The backend imports the canonical root `validator/` package (one level above
# backend/), and that package loads the SAP UoM master workbook at import time.
# Both must be present on the server next to backend/.
sudo cp -r validator "$APP_DIR/validator"
sudo mkdir -p "$APP_DIR/sample_data"
sudo cp sample_data/SAP_UOM_All.xlsx "$APP_DIR/sample_data/"

# Python virtual environment
sudo python3 -m venv "$APP_DIR/venv"
sudo "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"

echo "==> [4/7] Building React frontend..."
cd frontend
npm install
npm run build
cd ..

# Copy built files to web root
sudo mkdir -p "$STATIC_DIR"
sudo cp -r frontend/dist/. "$STATIC_DIR/"
sudo chown -R www-data:www-data "$STATIC_DIR"

echo "==> [5/7] Configuring Nginx..."
sudo cp deploy/nginx.conf /etc/nginx/sites-available/mmvalidator
sudo ln -sf /etc/nginx/sites-available/mmvalidator /etc/nginx/sites-enabled/mmvalidator
# Disable default site
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx

echo "==> [6/7] Installing systemd service..."
sudo cp deploy/mmvalidator.service /etc/systemd/system/mmvalidator.service

echo ""
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo "  ACTION REQUIRED: Edit the service file before"
echo "  starting the backend:"
echo "    sudo nano /etc/systemd/system/mmvalidator.service"
echo "  Set: MM_PASSWORD, JWT_SECRET (and optionally ANTHROPIC_API_KEY)"
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo ""

sudo systemctl daemon-reload
sudo systemctl enable mmvalidator

echo "==> [7/7] Opening firewall ports (80, 443)..."
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw --force enable

echo ""
echo "======================================================"
echo "  Setup complete!"
echo ""
echo "  NEXT STEPS:"
echo "  1. Edit /etc/systemd/system/mmvalidator.service"
echo "     and set MM_PASSWORD and JWT_SECRET"
echo "  2. sudo systemctl start mmvalidator"
echo "  3. sudo systemctl status mmvalidator   (check it's running)"
echo "  4. Open http://$(curl -s ifconfig.me) in your browser"
echo "  5. (Optional) Set up HTTPS with: sudo certbot --nginx"
echo "======================================================"
