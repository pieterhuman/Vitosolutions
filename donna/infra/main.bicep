// Donna Minimal — all processing inside the client's tenant.
// Deploy: az deployment group create -g <rg> -f infra/main.bicep \
//           -p appClientId=<app-registration-client-id>
//
// No secrets are set here. After deploy the operator puts exactly two
// secrets in Key Vault (see OPERATOR.md):
//   donna-close-hmac-key      random 64-byte key for mark-as-done links
//   donna-teams-webhook-url   Teams Workflows webhook (counts-only payloads)

@description('Azure region')
param location string = resourceGroup().location

@description('Resource name prefix')
param prefix string = 'donna'

@description('Client id of the single-tenant app registration')
param appClientId string

@description('Entra object id of the operator who administers Postgres')
param pgAdminObjectId string

@description('UPN of the operator who administers Postgres')
param pgAdminUpn string

var suffix = uniqueString(resourceGroup().id)
var funcName = '${prefix}-func-${suffix}'

// ---- identity (no client secrets anywhere) --------------------------------
resource mi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-mi'
  location: location
}

// ---- observability ----------------------------------------------------------
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 90
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-appi'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// ---- key vault ---------------------------------------------------------------
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${prefix}-kv-${suffix}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

// Key Vault Secrets User for the managed identity.
resource kvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, mi.id, 'kv-secrets-user')
  scope: keyVault
  properties: {
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

// ---- database: Postgres Flexible, Burstable, Entra-only auth ------------------
resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2023-12-01-preview' = {
  name: '${prefix}-pg-${suffix}'
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    storage: { storageSizeGB: 32 }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
      tenantId: subscription().tenantId
    }
    backup: { backupRetentionDays: 14, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
  }
}

resource pgAdmin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2023-12-01-preview' = {
  parent: pg
  name: pgAdminObjectId
  properties: {
    principalType: 'User'
    principalName: pgAdminUpn
    tenantId: subscription().tenantId
  }
}

resource pgDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-12-01-preview' = {
  parent: pg
  name: 'donna'
}

// Allow Azure services (the Function App) through the PG firewall.
resource pgFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-12-01-preview' = {
  parent: pg
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

// ---- function host --------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: '${prefix}st${suffix}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${prefix}-plan'
  location: location
  kind: 'linux'
  sku: { name: 'Y1', tier: 'Dynamic' }
  properties: { reserved: true }
}

resource funcApp 'Microsoft.Web/sites@2023-12-01' = {
  name: funcName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${mi.id}': {} }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'DONNA_TENANT_ID', value: subscription().tenantId }
        { name: 'DONNA_CLIENT_ID', value: appClientId }
        { name: 'DONNA_MI_CLIENT_ID', value: mi.properties.clientId }
        { name: 'DONNA_KEYVAULT_URI', value: keyVault.properties.vaultUri }
        { name: 'DONNA_DB_HOST', value: pg.properties.fullyQualifiedDomainName }
        { name: 'DONNA_DB_NAME', value: 'donna' }
        { name: 'DONNA_DB_USER', value: mi.name }
        { name: 'DONNA_DRY_RUN', value: '0' }
      ]
    }
  }
}

// Storage Blob Data Owner so the runtime can use identity-based storage.
resource stRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, mi.id, 'blob-owner')
  scope: storage
  properties: {
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'b7e6dc6d-f1e8-4753-8033-0f276bb0955b')
  }
}

// ---- heartbeat alert ---------------------------------------------------------------
// Fires when the heartbeat job logs DONNA_HEARTBEAT_MISSED (digest did not
// record success). The operator attaches their action group.
resource heartbeatAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: '${prefix}-heartbeat-missed'
  location: location
  properties: {
    displayName: 'Donna digest heartbeat missed'
    severity: 1
    enabled: true
    evaluationFrequency: 'PT15M'
    windowSize: 'PT30M'
    scopes: [ appInsights.id ]
    criteria: {
      allOf: [
        {
          query: 'traces | where message has "DONNA_HEARTBEAT_MISSED"'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    // actions: attach the operator-managed action group id here.
  }
}

output functionAppName string = funcApp.name
output managedIdentityClientId string = mi.properties.clientId
output managedIdentityPrincipalId string = mi.properties.principalId
output keyVaultName string = keyVault.name
output postgresHost string = pg.properties.fullyQualifiedDomainName
output closeEndpointBase string = 'https://${funcApp.properties.defaultHostName}/api'
