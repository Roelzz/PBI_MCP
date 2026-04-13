#!/bin/bash

# Azure App Registration Setup Script for Power BI MCP Server
# Creates an App Registration with Power BI API permissions and writes credentials to .env

set -e

# --- Configuration ---
POWERBI_RESOURCE_APP_ID="00000009-0000-0000-c000-000000000000"
PERM_DATASET_READ_ALL="7f33e027-4039-419b-938e-2f8ca153e68e"
PERM_WORKSPACE_READ_ALL="b2f1b2fa-f35c-407c-979c-a858a808ba85"
PERM_REPORT_READ_ALL="4ae1bf56-f562-4747-b7bc-2fa0874ed46f"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"

# --- Functions ---
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

update_env_value() {
    local key="$1"
    local value="$2"
    local file="$3"
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        sed -i '' "s|^${key}=.*|${key}=${value}|" "$file"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

# --- Check Prerequisites ---
if ! command_exists az; then
    echo "Azure CLI ('az') is not installed. Install it first:"
    echo "  brew install azure-cli (macOS)"
    echo "  curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash (Linux)"
    exit 1
fi

echo "Power BI MCP Server - Azure Auth Setup"
echo "======================================="
echo ""

# --- Check Login ---
echo "Checking Azure login status..."
ACCOUNT=$(az account show --query "user.name" -o tsv 2>/dev/null || echo "")
if [ -z "$ACCOUNT" ]; then
    echo "Not logged in. Opening browser for login..."
    az login >/dev/null
    ACCOUNT=$(az account show --query "user.name" -o tsv)
fi
TENANT_ID=$(az account show --query "tenantId" -o tsv)
echo "Logged in as: $ACCOUNT (Tenant: $TENANT_ID)"
echo ""

# --- Get App Name ---
read -p "Enter a name for the App Registration [PowerBI-MCP-Server]: " APP_NAME
APP_NAME=${APP_NAME:-PowerBI-MCP-Server}

# --- Create App Registration ---
echo "Creating App Registration '$APP_NAME'..."
APP_ID=$(az ad app create --display-name "$APP_NAME" --query "appId" -o tsv)
echo "App created. Client ID: $APP_ID"

# --- Create Service Principal ---
echo "Creating Service Principal..."
SP_ID=$(az ad sp create --id "$APP_ID" --query "id" -o tsv)
echo "Service Principal created."

# --- Create Client Secret ---
echo "Generating Client Secret (1 year expiry)..."
CLIENT_SECRET=$(az ad app credential reset --id "$APP_ID" --append --display-name "MCP Server Secret" --years 1 --query "password" -o tsv)
echo "Client Secret generated."

# --- Add Power BI Permissions ---
echo "Adding Dataset.Read.All permission (required)..."
az ad app permission add --id "$APP_ID" --api "$POWERBI_RESOURCE_APP_ID" --api-permissions "$PERM_DATASET_READ_ALL=Role" >/dev/null

echo "Adding Workspace.Read.All permission (optional, for cross-workspace discovery)..."
az ad app permission add --id "$APP_ID" --api "$POWERBI_RESOURCE_APP_ID" --api-permissions "$PERM_WORKSPACE_READ_ALL=Role" >/dev/null

echo "Adding Report.Read.All permission (optional, for cross-workspace report access)..."
az ad app permission add --id "$APP_ID" --api "$POWERBI_RESOURCE_APP_ID" --api-permissions "$PERM_REPORT_READ_ALL=Role" >/dev/null

echo "Attempting to grant Admin Consent..."
if az ad app permission admin-consent --id "$APP_ID" 2>/dev/null; then
    echo "Admin Consent granted."
else
    echo ""
    echo "WARNING: Could not grant Admin Consent automatically (requires Global Admin)."
    echo "  Go to: Azure Portal > App Registrations > $APP_NAME > API Permissions"
    echo "  Click 'Grant admin consent for [Your Org]'"
fi

# --- Write .env ---
echo ""
echo "Writing credentials to .env..."
if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$ENV_EXAMPLE" ]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        echo "Created .env from .env.example"
    else
        touch "$ENV_FILE"
        echo "Created empty .env"
    fi
fi

update_env_value "TENANT_ID" "$TENANT_ID" "$ENV_FILE"
update_env_value "CLIENT_ID" "$APP_ID" "$ENV_FILE"
update_env_value "CLIENT_SECRET" "$CLIENT_SECRET" "$ENV_FILE"
echo ".env updated with credentials."

# --- Summary ---
echo ""
echo "Setup complete!"
echo "======================================="
echo "TENANT_ID=$TENANT_ID"
echo "CLIENT_ID=$APP_ID"
echo "CLIENT_SECRET=****${CLIENT_SECRET: -4}"
echo "======================================="
echo ""
echo "MANUAL STEPS REQUIRED:"
echo ""
echo "1. Power BI Admin Portal (admin.powerbi.com):"
echo "   Settings > Tenant settings > Developer settings"
echo "   Enable 'Allow service principals to use Power BI APIs'"
echo "   Add the service principal (or its security group) to the allowed list."
echo ""
echo "2. Power BI Workspace:"
echo "   Open your workspace > Settings > Access"
echo "   Add '$APP_NAME' as a Member (or Contributor)."
echo "   This grants Build permission on datasets in that workspace."
echo ""
echo "3. Test the server:"
echo "   uv run python main.py"
