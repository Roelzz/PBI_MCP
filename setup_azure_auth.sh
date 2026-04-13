#!/bin/bash

# Azure App Registration Setup Script for Power BI MCP Server
# Creates an App Registration with certificate auth, Power BI permissions,
# and optional OBO (On-Behalf-Of) configuration.

set -e

# --- Configuration ---
POWERBI_RESOURCE_APP_ID="00000009-0000-0000-c000-000000000000"
# Delegated permissions (Scope) — least privilege for OBO
PERM_DATASET_READ_ALL="322b68b2-0804-416e-86a5-d772c567f6be"
PERM_WORKSPACE_READ_ALL="47df08d4-1c52-4b89-89ee-980e926801d7"
PERM_REPORT_READ_ALL="4ae1bf56-f562-4747-b7bc-2fa0874ed46f"
PERM_SEMANTIC_MODEL_READWRITE_ALL="8ebba963-9494-4133-907f-f29e6a1a44a3"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"
CERT_DIR="$SCRIPT_DIR"

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

if ! command_exists openssl; then
    echo "OpenSSL is not installed. Install it first."
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
OBJECT_ID=$(az ad app show --id "$APP_ID" --query "id" -o tsv)
echo "App created. Client ID: $APP_ID"

# --- Create Service Principal ---
echo "Creating Service Principal..."
SP_ID=$(az ad sp create --id "$APP_ID" --query "id" -o tsv)
echo "Service Principal created."

# --- Generate Certificate ---
echo "Generating self-signed certificate (1 year)..."
openssl req -x509 -newkey rsa:2048 \
    -keyout "$CERT_DIR/private.key" \
    -out "$CERT_DIR/cert.pem" \
    -days 365 -nodes \
    -subj "/CN=$APP_NAME" 2>/dev/null

openssl pkcs12 -export \
    -out "$CERT_DIR/cert.pfx" \
    -inkey "$CERT_DIR/private.key" \
    -in "$CERT_DIR/cert.pem" \
    -passout pass: 2>/dev/null

echo "Uploading certificate to App Registration..."
az ad app credential reset --id "$APP_ID" --cert @"$CERT_DIR/cert.pem" --append >/dev/null
rm -f "$CERT_DIR/private.key"
echo "Certificate created: cert.pfx (keep this secure)"

# --- Add Delegated Permissions (least privilege for OBO) ---
echo ""
echo "Adding delegated permissions..."
az ad app permission add --id "$APP_ID" --api "$POWERBI_RESOURCE_APP_ID" --api-permissions "$PERM_DATASET_READ_ALL=Scope" >/dev/null
echo "  Dataset.Read.All (Delegated) — list/get datasets, execute DAX"
az ad app permission add --id "$APP_ID" --api "$POWERBI_RESOURCE_APP_ID" --api-permissions "$PERM_WORKSPACE_READ_ALL=Scope" >/dev/null
echo "  Workspace.Read.All (Delegated) — list workspaces"
az ad app permission add --id "$APP_ID" --api "$POWERBI_RESOURCE_APP_ID" --api-permissions "$PERM_REPORT_READ_ALL=Scope" >/dev/null
echo "  Report.Read.All (Delegated) — list reports"
az ad app permission add --id "$APP_ID" --api "$POWERBI_RESOURCE_APP_ID" --api-permissions "$PERM_SEMANTIC_MODEL_READWRITE_ALL=Scope" >/dev/null
echo "  SemanticModel.ReadWrite.All (Delegated) — get schema (no read-only alternative exists)"

# --- Grant Admin Consent + Explicit Scope Grant ---
echo ""
echo "Attempting to grant Admin Consent..."
if az ad app permission admin-consent --id "$APP_ID" 2>/dev/null; then
    echo "Admin Consent granted."
else
    echo ""
    echo "WARNING: Could not grant Admin Consent automatically (requires Global Admin)."
    echo "  Go to: Azure Portal > App Registrations > $APP_NAME > API Permissions"
    echo "  Click 'Grant admin consent for [Your Org]'"
fi

echo "Granting explicit scope consent..."
az ad app permission grant --id "$APP_ID" --api "$POWERBI_RESOURCE_APP_ID" \
    --scope "Dataset.Read.All Workspace.Read.All Report.Read.All SemanticModel.ReadWrite.All" >/dev/null 2>&1 || true
echo "Scope grant applied."

# --- Expose API Scope (for OBO) ---
echo ""
echo "Configuring OBO: exposing API scope..."
az ad app update --id "$APP_ID" --identifier-uris "api://$APP_ID" >/dev/null

SCOPE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
az rest --method PATCH \
    --uri "https://graph.microsoft.com/v1.0/applications/$OBJECT_ID" \
    --body "{\"api\":{\"requestedAccessTokenVersion\":2,\"oauth2PermissionScopes\":[{\"id\":\"$SCOPE_ID\",\"adminConsentDescription\":\"Access Power BI MCP server on behalf of user\",\"adminConsentDisplayName\":\"Access as user\",\"isEnabled\":true,\"type\":\"User\",\"value\":\"access_as_user\"}]}}" >/dev/null
echo "Exposed scope: api://$APP_ID/access_as_user"

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
update_env_value "CLIENT_CERT_PATH" "$CERT_DIR/cert.pfx" "$ENV_FILE"
update_env_value "AUTH_MODE" "none" "$ENV_FILE"
echo ".env updated with credentials."

# --- Summary ---
echo ""
echo "Setup complete!"
echo "======================================="
echo "TENANT_ID=$TENANT_ID"
echo "CLIENT_ID=$APP_ID"
echo "CLIENT_CERT_PATH=$CERT_DIR/cert.pfx"
echo "API Scope: api://$APP_ID/access_as_user"
echo "======================================="
echo ""
echo "AUTH MODES:"
echo ""
echo "  AUTH_MODE=none (default):"
echo "    Uses certificate credentials to access Power BI."
echo "    No authentication on the MCP endpoint."
echo ""
echo "  AUTH_MODE=obo:"
echo "    Requires Azure AD bearer token on every MCP request."
echo "    Exchanges user token for Power BI token via OBO flow."
echo "    Set MCP_BASE_URL to the server's public URL."
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
echo ""
echo "3. Test the server:"
echo "   uv run python main.py"
