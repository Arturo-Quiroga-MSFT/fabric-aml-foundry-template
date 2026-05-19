// =============================================================================
// Contoso POC — Fabric + Azure ML test bed
// Deploys: Storage, Key Vault, Log Analytics, App Insights, ACR, User-Assigned MI,
//          AML workspace, AML compute cluster, AML compute instance.
// Scope:   resourceGroup
// =============================================================================

targetScope = 'resourceGroup'

@description('Short name used as a prefix for all resources. Lowercase letters/numbers, <= 12 chars.')
@maxLength(12)
param namePrefix string = 'contoso'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Object ID of the developer / deployer principal (you). Receives AzureML Data Scientist + Contributor on the workspace.')
param developerPrincipalId string

@description('Compute instance owner UPN (email) — required for AML compute instance.')
param computeInstanceOwnerUpn string

@description('VM size for the AutoML / training compute cluster.')
param trainingVmSize string = 'Standard_DS3_v2'

@description('Max nodes for the training cluster (autoscales 0 -> max).')
param trainingMaxNodes int = 4

@description('VM size for the interactive compute instance.')
param computeInstanceVmSize string = 'Standard_DS3_v2'

@description('Tags applied to all resources.')
param tags object = {
  project: 'contoso-poc'
  workload: 'fabric-aml'
  owner: 'psa-team'
}

@description('Deploy AML workspace + computes. Set to false on first deploy (creates UAMI + RBAC), then true on second deploy after RBAC propagates (~2 min).')
param deployAml bool = true

@description('Optional container app name. Leave empty to use generated name.')
param containerAppName string = 'mcp-server'

@description('Container app image.')
param containerAppImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('External ingress target port exposed by the container app.')
param containerAppTargetPort int = 9000

@description('Container app CPU cores.')
param containerAppCpu int = 1

@description('Container app memory value (for example: 1Gi, 2Gi).')
param containerAppMemory string = '2Gi'

@description('Minimum number of replicas for the container app.')
param containerAppMinReplicas int = 1

@description('Maximum number of replicas for the container app.')
param containerAppMaxReplicas int = 2

@description('Deploy the Container Apps Environment + Container App. Requires the two referenced Key Vault secrets (aml-endpoint-token, application-insights-connection-string) to already exist in the shared Key Vault.')
param deployContainerApp bool = true

// -----------------------------------------------------------------------------
// Naming
// -----------------------------------------------------------------------------
var uniq = uniqueString(resourceGroup().id)
var saName  = toLower('${namePrefix}st${substring(uniq, 0, 6)}')
var kvName  = toLower('${namePrefix}-kv-${substring(uniq, 0, 5)}')
var lawName = toLower('${namePrefix}-law-${substring(uniq, 0, 5)}')
var aiName  = toLower('${namePrefix}-ai-${substring(uniq, 0, 5)}')
var acrName = toLower('${namePrefix}acr${substring(uniq, 0, 6)}')
var miName  = toLower('${namePrefix}-mi-${substring(uniq, 0, 5)}')
var amlName = toLower('${namePrefix}-aml-${substring(uniq, 0, 5)}2')
var caeName = toLower('${namePrefix}-cae-${substring(uniq, 0, 5)}')
var caName = empty(containerAppName) ? toLower('${namePrefix}-ca-${substring(uniq, 0, 5)}') : toLower(containerAppName)

// -----------------------------------------------------------------------------
// User-Assigned Managed Identity
// -----------------------------------------------------------------------------
resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: miName
  location: location
  tags: tags
}

// -----------------------------------------------------------------------------
// Storage account (AML default storage)
// Note: AML workspace default storage must NOT have HNS enabled.
// -----------------------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: saName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: false
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
  }
}

// -----------------------------------------------------------------------------
// Key Vault (RBAC-mode)
// -----------------------------------------------------------------------------
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
  }
}

// -----------------------------------------------------------------------------
// Log Analytics + Application Insights
// -----------------------------------------------------------------------------
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: aiName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// -----------------------------------------------------------------------------
// Container Registry
// -----------------------------------------------------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

// -----------------------------------------------------------------------------
// UAMI role assignments (must exist BEFORE the AML workspace is created so the
// workspace identity can read its dependent resources during provisioning).
// -----------------------------------------------------------------------------

// Storage Blob Data Contributor on AML default storage -> UAMI
resource raStorageUami 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, uami.id, 'StorageBlobDataContributor')
  scope: storage
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}

// Key Vault Secrets User -> UAMI
resource raKvUami 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, uami.id, 'KeyVaultSecretsUser')
  scope: kv
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

// AcrPull -> UAMI
resource raAcrUami 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, uami.id, 'AcrPull')
  scope: acr
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

// Contributor on the resource group -> UAMI
// Lets the AML workspace read dependent resources (KV, Storage, ACR, App Insights)
// during workspace provisioning when the UAMI is the workspace primary identity.
resource raRgUami 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, uami.id, 'Contributor')
  scope: resourceGroup()
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c')
  }
}

// -----------------------------------------------------------------------------
// Container Apps (external ingress) reusing shared infra resources
//
// NOTE: Key Vault secrets are referenced as 'existing' so this template never
// overwrites their values. Create/populate them out-of-band (CLI, portal, or a
// separate bootstrap pipeline) before deploying with deployContainerApp=true.
// -----------------------------------------------------------------------------
resource kvSecretAppInsightsConnString 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = if (deployContainerApp) {
  parent: kv
  name: 'application-insights-connection-string'
}

resource kvSecretAmlEndpointToken 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = if (deployContainerApp) {
  parent: kv
  name: 'aml-endpoint-token'
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = if (deployContainerApp) {
  name: caeName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = if (deployContainerApp) {
  name: caName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: cae!.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: acr.properties.loginServer
          identity: uami.id
        }
      ]
      ingress: {
        external: true
        targetPort: containerAppTargetPort
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        corsPolicy: {
          allowedOrigins: [
            '*'
          ]
          allowedMethods: [
            'GET'
            'POST'
            'PUT'
            'DELETE'
            'OPTIONS'
          ]
          allowedHeaders: [
            '*'
          ]
          exposeHeaders: [
            '*'
          ]
          allowCredentials: false
          maxAge: 3600
        }
      }
      secrets: [
        {
          name: 'aml-endpoint-token'
          keyVaultUrl: kvSecretAmlEndpointToken!.properties.secretUri
          identity: uami.id
        }
        {
          name: 'application-insights-connection-string'
          keyVaultUrl: kvSecretAppInsightsConnString!.properties.secretUri
          identity: uami.id
        }        
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: containerAppImage
          resources: {
            cpu: containerAppCpu
            memory: containerAppMemory
          }
          env: [
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'application-insights-connection-string'
            }
            {
              name: 'AML_ENDPOINT_TOKEN'
              secretRef: 'aml-endpoint-token'
            }
            {
              name: 'AML_ENDPOINT_URL'
              value: '' 
            }            
          ]
        }
      ]
      scale: {
        minReplicas: containerAppMinReplicas
        maxReplicas: containerAppMaxReplicas
      }
    }
  }
  dependsOn: [
    raAcrUami
    raKvUami
  ]
}

// -----------------------------------------------------------------------------
// Azure ML workspace
// -----------------------------------------------------------------------------
resource aml 'Microsoft.MachineLearningServices/workspaces@2024-04-01' = if (deployAml) {
  name: amlName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    friendlyName: 'Fabric + AML Foundry Template'
    storageAccount: storage.id
    keyVault: kv.id
    applicationInsights: appi.id
    containerRegistry: acr.id
    publicNetworkAccess: 'Enabled'
    primaryUserAssignedIdentity: uami.id
    hbiWorkspace: false
  }
  dependsOn: [
    raStorageUami
    raKvUami
    raAcrUami
    raRgUami
  ]
}

// -----------------------------------------------------------------------------
// AML compute cluster (training / AutoML)
// -----------------------------------------------------------------------------
resource cluster 'Microsoft.MachineLearningServices/workspaces/computes@2024-04-01' = if (deployAml) {
  parent: aml
  name: 'cpu-cluster'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    computeType: 'AmlCompute'
    properties: {
      vmSize: trainingVmSize
      vmPriority: 'Dedicated'
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: trainingMaxNodes
        nodeIdleTimeBeforeScaleDown: 'PT300S'
      }
      remoteLoginPortPublicAccess: 'Disabled'
    }
  }
}

// -----------------------------------------------------------------------------
// AML compute instance (interactive notebooks)
// -----------------------------------------------------------------------------
resource ci 'Microsoft.MachineLearningServices/workspaces/computes@2024-04-01' = if (deployAml) {
  parent: aml
  name: 'ci-${substring(uniq, 0, 5)}'
  location: location
  properties: {
    computeType: 'ComputeInstance'
    properties: {
      vmSize: computeInstanceVmSize
      personalComputeInstanceSettings: {
        assignedUser: {
          objectId: developerPrincipalId
          tenantId: subscription().tenantId
        }
      }
      // assignedUserUpn used for display only via tags:
    }
  }
  tags: union(tags, {
    assignedUserUpn: computeInstanceOwnerUpn
  })
}

// =============================================================================
// Developer role assignments
// =============================================================================

// AzureML Data Scientist -> developer
resource raAmlDeveloper 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployAml) {
  name: guid(aml.id, developerPrincipalId, 'AzureMLDataScientist')
  scope: aml
  properties: {
    principalId: developerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'f6c7c914-8db3-469d-8ca1-694a8f32e121')
  }
}

// Key Vault Secrets Officer -> developer (so you can write secrets from your laptop)
resource raKvDeveloper 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, developerPrincipalId, 'KeyVaultSecretsOfficer')
  scope: kv
  properties: {
    principalId: developerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7')
  }
}

// =============================================================================
// Outputs
// =============================================================================
output resourceGroupName string = resourceGroup().name
output amlWorkspaceName string = deployAml ? aml.name : ''
output storageAccountName string = storage.name
output keyVaultName string = kv.name
output appInsightsName string = appi.name
output logAnalyticsName string = law.name
output containerRegistryName string = acr.name
output managedIdentityName string = uami.name
output managedIdentityClientId string = uami.properties.clientId
output managedIdentityPrincipalId string = uami.properties.principalId
output computeClusterName string = deployAml ? cluster.name : ''
output computeInstanceName string = deployAml ? ci.name : ''
output containerAppEnvironmentName string = deployContainerApp ? cae!.name : ''
output containerAppName string = deployContainerApp ? app!.name : ''
output containerAppFqdn string = deployContainerApp ? app!.properties.configuration.ingress.fqdn : ''
output containerAppUrl string = deployContainerApp ? 'https://${app!.properties.configuration.ingress.fqdn}' : ''
