# main.tf — Spheron multi-GPU spot node for the remvllm appliance.
#
# Contract: "get me gpu_count GPUs of gpu_type on a SPOT node that can run podman
# with GPU passthrough." cloud-init installs podman + nvidia-container-toolkit
# and runs the appliance container. Mirrors the remollama Spheron module, with
# multi-GPU and spot pricing added.

terraform {
  required_providers {
    spheron = {
      source  = "spheronFdn/spheron"
      version = ">= 1.0.0"
    }
  }
}

provider "spheron" {
  token = var.provider_token
}

resource "spheron_instance" "remvllm" {
  name = var.instance_name

  # Sizer-driven multi-GPU request.
  gpu_type  = var.gpu_type
  gpu_count = var.gpu_count

  # Cheapest-first: spot by default, optional price cap.
  spot      = var.spot
  max_price = var.max_price > 0 ? var.max_price : null

  ssh_public_key = var.ssh_public_key

  # cloud-init: install podman + nvidia-container-toolkit, run the appliance.
  user_data = templatefile("${path.module}/scripts/bootstrap.sh", {
    container_image = var.container_image
    ssh_public_key  = var.ssh_public_key
    env_vars        = var.env_vars
  })
}
