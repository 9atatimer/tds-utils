# outputs.tf — provider-agnostic contract outputs.

output "host" {
  value       = spheron_instance.remvllm.ip
  description = "Instance IP or hostname"
}

output "ssh_port" {
  value       = spheron_instance.remvllm.ssh_port
  description = "SSH port on the instance"
}

output "instance_id" {
  value       = spheron_instance.remvllm.id
  description = "Provider-specific instance identifier"
}
