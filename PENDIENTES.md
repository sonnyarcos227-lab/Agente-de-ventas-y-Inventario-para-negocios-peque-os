# Pendientes de confirmar con Decorer

Mientras no estén, el agente responde "eso lo confirma un asesor" y deja el caso en `v_pendientes_asesor`.
Cuando tengas el dato, cámbialo en `database/02_parametros_decorer.sql` (o en la tabla `parametros`) y en los `.md` de `conocimiento/`.

## Para que el agente pueda vender

- [x] **Precios de venta**: cargados de la lista general de SysCafé (2.323 artículos).
- [ ] **20 artículos sin precio**, 5 de ellos con existencias: Tocador Hawai (4), Escritorio y tocador (2), Espuma Renacer 1.20, Sofá Germany microcuero y Somier Armonía 1.00 cuerina. Escribe su precio en la columna `precio_venta` de `importar/ajustes_decorer.csv`.
- [ ] **Conteo físico** (opcional; mientras tanto lo que no tiene saldo positivo queda agotado o por encargo) de lo que hay en el almacén: columna `existencias_reales` de `importar/ajustes_decorer.csv` (ábrelo con Excel; los artículos con saldo positivo en SysCafé están de primeros). Hoy solo 50 artículos tienen saldo positivo en SysCafé; todo lo demás el agente lo muestra como agotado o por encargo.
- [x] Los precios no llevan IVA por ahora: son el valor final.
- [x] WhatsApp de la tienda: 322 378 7495.

## Reglas del negocio

- [ ] Costo del domicilio en la zona urbana para compras de menos de $500.000 (`domicilio_urbano_mocoa`).
- [ ] ¿Llevan a veredas o a otros municipios (Villagarzón, Puerto Asís...)? ¿Con qué costo?
- [ ] ¿En cuántos días se entrega un pedido? (`dias_entrega`). Es una de las preguntas más frecuentes.
- [ ] ¿El domicilio incluye armar el mueble?
- [ ] Separado: abono mínimo (%) y plazo para terminar de pagar (`separado_abono_minimo_pct`, `separado_plazo_dias`). ¿Qué pasa con el abono si el cliente desiste?
- [ ] Crédito personal con Decorer: ¿qué requisitos pide la tienda (cédula, fiador, cuota inicial)?
- [ ] ¿Reciben tarjeta (datáfono)? En las formas de pago solo quedaron efectivo y transferencia.
- [ ] ¿Abren domingos o festivos?
- [ ] SysCafé tiene códigos de servicios (tapizado, cambio de color, fabricación en RH a la medida). ¿Se ofrecen al cliente? Si sí, los agrego como servicios con su política.

## Ajuste legal (para revisar con tu prima)

La política que me diste dice que, pasados 7 días, la garantía "se solicita directamente con la marca". Por la Ley 1480 (art. 10) la tienda y la marca responden juntas ante el cliente: el cliente puede reclamar en Decorer y la tienda gestiona con la marca. Así quedó redactado en `politicas.md`. También se agregó el derecho de retracto de 5 días hábiles, que aplica a las ventas que haga el agente por chat o voz.
