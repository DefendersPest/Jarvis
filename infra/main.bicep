// JARVIS - Azure infrastructure (Phase 1)
//
// NOT DEPLOYED. Review, then deploy only after approval:
//   az group create -n rg-jarvis-prod -l eastus2
//   az deployment group create -g rg-jarvis-prod -f infra/main.bicep -p infra/main.parameters.example.json
//
// Everything is passwordless: the Function App's managed identity reads Key
// Vault, the storage account and Azure SQL. No connection string with a secret
// exists anywhere.

targetScope = 'resourceGroup'

@description('Short environment name used in resource names.')
@allowed(['dev', 'prod'])
param env string = 'prod'

param location string = resourceGroup().location

@description('Base name, lowercase letters/digits only.')
param baseName string = 'jarvis'

@description('Entra ID group that administers Azure SQL (e.g. "JARVIS SQL Admins").')
param sqlAdminGroupName string

@description('Object ID of that Entra ID group.')
param sqlAdminGroupObjectId string

@description('E-mail that receives failure alerts and budget warnings.')
param alertEmail string

@description('Monthly Azure budget (USD) for this resource group; alerts at 80% and 100%.')
param monthlyBudgetUsd int = 150

@description('Budget start date - first day of a month, e.g. 2026-11-01.')
param budgetStartDate string

var suffix = uniqueString(resourceGroup().id)
var name = '${baseName}-${env}'
var storageName = toLower('st${baseName}${env}${take(suffix, 6)}')
var kvName = 'kv-${name}-${take(suffix, 6)}'
var deploymentContainer = 'app-package'
var tags = { app: 'jarvis', env: env, owner: 'The Defenders' }

// ---------------------------------------------------------------- monitoring
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${name}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 } // cost guardrail
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${name}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// ---------------------------------------------------------------- storage (Functions runtime + deployment package)
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false // identity-only access
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource packageContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: deploymentContainer
}

// ---------------------------------------------------------------- key vault
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled' // Phase 3: private endpoint
  }
}

// ---------------------------------------------------------------- azure sql (serverless, free offer first)
resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: 'sql-${name}-${take(suffix, 6)}'
  location: location
  tags: tags
  properties: {
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled' // Phase 3: private endpoint
    administrators: {
      administratorType: 'ActiveDirectory'
      azureADOnlyAuthentication: true // no SQL logins / passwords at all
      login: sqlAdminGroupName
      sid: sqlAdminGroupObjectId
      tenantId: subscription().tenantId
      principalType: 'Group'
    }
  }
}

resource sqlAllowAzure 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sqlServer
  name: 'AllowAzureServices' // lets the Function App and Power BI service connect
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource sqlDb 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: 'jarvis'
  location: location
  tags: tags
  sku: { name: 'GP_S_Gen5_2', tier: 'GeneralPurpose', family: 'Gen5', capacity: 2 }
  properties: {
    autoPauseDelay: 60
    minCapacity: json('0.5')
    useFreeLimit: true                       // Azure SQL free offer: 100k vCore-seconds + 32 GB / month
    freeLimitExhaustionBehavior: 'BillOverUsage' // never pause the CEO report; pay the small overage instead
    requestedBackupStorageRedundancy: 'Local'
    zoneRedundant: false
  }
}

// ---------------------------------------------------------------- function app (Flex Consumption)
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'asp-${name}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: { tier: 'FlexConsumption', name: 'FC1' }
  properties: { reserved: true }
}

resource func 'Microsoft.Web/sites@2024-04-01' = {
  name: 'func-${name}-${take(suffix, 6)}'
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'JARVIS_ENV', value: env }
        { name: 'JARVIS_DATABASE_URL', value: 'mssql+pyodbc://@${sqlServer.properties.fullyQualifiedDomainName}/jarvis?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no' }
        { name: 'JARVIS_KEY_VAULT_URL', value: kv.properties.vaultUri }
        { name: 'JARVIS_TIMEZONE', value: 'America/New_York' }
        { name: 'JARVIS_REPORT_HOUR_LOCAL', value: '6' }
        // Safe defaults: sample data and dry run until go-live is approved.
        { name: 'JARVIS_DATA_SOURCE', value: 'sample' }
        { name: 'JARVIS_DRY_RUN', value: 'true' }
        { name: 'JARVIS_OUTPUT_DIR', value: '/tmp/jarvis-out' }
        { name: 'JARVIS_AI_PROVIDER', value: 'anthropic' }
        { name: 'JARVIS_AI_MODEL', value: 'claude-opus-5-5' }
      ]
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deploymentContainer}'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: { maximumInstanceCount: 10, instanceMemoryMB: 2048 }
      runtime: { name: 'python', version: '3.11' }
    }
  }
}

// ---------------------------------------------------------------- RBAC for the function's managed identity
var roles = {
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  blobOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  queueContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  tableContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
}

resource kvRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, func.id, roles.kvSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsUser)
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in [roles.blobOwner, roles.queueContributor, roles.tableContributor]: {
  scope: storage
  name: guid(storage.id, func.id, r)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
  }
}]

// ---------------------------------------------------------------- alerting
resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-${name}'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'jarvis'
    enabled: true
    emailReceivers: [{ name: 'owner', emailAddress: alertEmail, useCommonAlertSchema: true }]
  }
}

resource reportFailedAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-${name}-report-failed'
  location: location
  tags: tags
  properties: {
    displayName: 'JARVIS CEO report failed'
    severity: 1
    enabled: true
    scopes: [appInsights.id]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT15M'
    criteria: {
      allOf: [
        {
          query: 'union requests, exceptions | where operation_Name startswith "ceo_daily_report" | where success == false or itemType == "exception"'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: { actionGroups: [actionGroup.id] }
  }
}

// Dead-man's switch: alerts if no report finished by ~7 AM Eastern on a weekday.
resource reportMissingAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-${name}-report-missing'
  location: location
  tags: tags
  properties: {
    displayName: 'JARVIS CEO report did not run'
    severity: 1
    enabled: true
    scopes: [appInsights.id]
    evaluationFrequency: 'PT1H'
    windowSize: 'P1D'
    criteria: {
      allOf: [
        {
          query: 'let now_et = datetime_utc_to_local(now(), "America/New_York"); let is_check_time = dayofweek(now_et) between (1d .. 5d) and hourofday(now_et) == 7; traces | where message has "ceo_report.done" | where datetime_utc_to_local(timestamp, "America/New_York") > startofday(now_et) | summarize runs = count() | where is_check_time and runs == 0'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: { actionGroups: [actionGroup.id] }
  }
}

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: 'budget-${name}'
  properties: {
    category: 'Cost'
    amount: monthlyBudgetUsd
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStartDate }
    notifications: {
      actual80: { enabled: true, operator: 'GreaterThan', threshold: 80, contactEmails: [alertEmail] }
      forecast100: { enabled: true, operator: 'GreaterThan', threshold: 100, thresholdType: 'Forecasted', contactEmails: [alertEmail] }
    }
  }
}

output functionAppName string = func.name
output functionPrincipalId string = func.identity.principalId
output keyVaultName string = kv.name
output sqlServerFqdn string = sqlServer.properties.fullyQualifiedDomainName
