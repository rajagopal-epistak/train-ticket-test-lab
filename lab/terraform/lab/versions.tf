terraform {
  required_version = ">= 1.8.0"
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.3"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.2"
    }
    datadog = {
      source  = "DataDog/datadog"
      version = "~> 4.22"
    }
  }
}

provider "kubernetes" {
  config_path = var.kubeconfig
}

provider "helm" {
  kubernetes = {
    config_path = var.kubeconfig
  }
}

# api_key and app_key come from DD_API_KEY / DD_APP_KEY in the environment.
provider "datadog" {
  api_url = "https://api.${var.dd_site}/"
}
