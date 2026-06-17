# variables.tf — provider-agnostic contract inputs (+ multi-GPU/spot extensions).

variable "gpu_type" {
  type        = string
  description = "GPU tier: a100 | h100 | h200 | b200"
}

variable "gpu_count" {
  type        = number
  description = "Number of GPUs (tensor-parallel size), from the remvllm sizer"
}

variable "spot" {
  type        = bool
  default     = true
  description = "Provision a spot/preemptible node (cheapest; may be reclaimed)"
}

variable "max_price" {
  type        = number
  default     = 0
  description = "Max spot price per hour (0 = provider default / no cap)"
}

variable "container_image" {
  type        = string
  description = "Appliance image to run (vLLM + sshd + watchdog)"
}

variable "ssh_public_key" {
  type        = string
  description = "SSH public key injected for tunnel access"
}

variable "provider_token" {
  type        = string
  sensitive   = true
  description = "Spheron API credential (from 1Password at runtime)"
}

variable "instance_name" {
  type        = string
  description = "Name tag for the instance"
}

variable "env_vars" {
  type        = map(string)
  default     = {}
  description = "Environment variables for the appliance container"
}
