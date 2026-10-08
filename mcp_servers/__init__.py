"""Servidores MCP: un servidor por sistema de negocio (decisión 2.2).

Cada sistema se conecta una vez y queda disponible para todo agente que lo
declare. Los servidores no saben qué agente los llama ni validan permisos: eso
lo hace el runtime antes de llamarlos. Aquí solo vive el acceso al sistema.

Corren como subprocesos por stdio (`python -m mcp_servers.<nombre>`), como en un
agente anterior. En producción serían servicios HTTP dentro de la red
de la empresa, uno por sistema, con sus propias credenciales de solo lectura o de
escritura según la herramienta.
"""
