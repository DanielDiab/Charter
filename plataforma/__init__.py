"""Charter: plataforma de agentes — prototipo del corte vertical de la propuesta.

Ver docs/DECISIONES.md para el mapa entre el documento de arquitectura y este código.
"""

import warnings

# Advertencia interna de pydantic-settings al importar `mcp` 1.28 en Python 3.14.
# No afecta el funcionamiento; se silencia para que la terminal muestre solo la demo.
warnings.filterwarnings("ignore", message=r"Field 'lifespan' has an incomplete definition")
