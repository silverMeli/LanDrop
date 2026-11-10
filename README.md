# LanDrop

Envía archivos entre tu PC con Windows, tu celular (iPhone o Android) y otras PCs, por la misma red WiFi. Funciona parecido a AirDrop y Quick Share: sin cables, sin internet y sin instalar nada en el celular.

## Dos apps que se encuentran solas

- **LanDrop para Windows** (`LanDrop.exe`)
- **LanDrop para Android** (`LanDrop.apk`, carpeta `android/`)

Abre las dos en la misma WiFi y cada una ve a la otra en **Dispositivos cercanos**, sin QR. El QR queda para iPhones o celulares sin la app.

### En el Android
- Toca una PC → **Fotos**, **Archivos** o **Texto**.
- Desde la galería o cualquier app: **Compartir → LanDrop** → toca la PC.
- Para recibir desde la PC, deja LanDrop abierto en pantalla. Lo recibido se guarda en `Descargas/LanDrop`.
- Si marcas **Aceptar siempre de este dispositivo**, ya no te pregunta (se puede quitar en la PC con el botón *De confianza…*).

## Qué puede hacer

| De → A | Cómo |
|---|---|
| **Celular → PC** | Escanea el QR de la ventana de LanDrop con la cámara, toca *Elegir fotos, videos o archivos*. |
| **PC → Celular** | En LanDrop: *Enviar al celular → Agregar archivos…*. Aparecen en la página del celular con un botón *Descargar*. |
| **PC ↔ PC / Android** | Los dispositivos con LanDrop abierto aparecen solas en *PCs cercanas*. Doble clic, eliges archivos y la otra PC ve un aviso **Aceptar / Rechazar** (como AirDrop). También se pueden enviar carpetas completas. |
| **Texto / enlaces** | Desde el celular se copia directo al portapapeles de la PC (si es un enlace, un botón lo abre). Desde la PC: *Enviar portapapeles*. |
| **Clic derecho** | Botón *Agregar a "Enviar a"*: luego clic derecho en cualquier archivo → *Enviar a → LanDrop* y eliges el destino. También puedes arrastrar archivos sobre el ícono de LanDrop.exe. |

Los archivos recibidos se guardan en `Descargas\LanDrop` (se puede cambiar).

## Obtener el .exe con GitHub Actions (sin instalar Python)

1. Crea un repositorio nuevo en GitHub (por ejemplo `LanDrop`) y sube **todos** estos archivos, incluyendo la carpeta `.github/workflows`.
2. Ve a la pestaña **Actions**. La compilación arranca sola con cada cambio (o con *Run workflow*).
3. Cuando termine (unos 2–3 minutos), abre la ejecución y descarga el artefacto **LanDrop-windows**. Adentro está `LanDrop.exe`.

## Obtener el APK de Android

En **Actions** → *Compilar LanDrop Android* → artefacto **LanDrop-android** → `LanDrop.apk`. Instálalo desde el celular (permite "instalar apps desconocidas" para el navegador o Mis archivos). Las siguientes versiones se instalan encima sin desinstalar.

## Primera vez en Windows

- **SmartScreen** puede decir "Windows protegió su PC" porque el .exe no está firmado: *Más información → Ejecutar de todas formas*.
- **Firewall:** cuando Windows pregunte, marca **Redes privadas** y da *Permitir acceso*. Sin esto el celular y las otras PCs no podrán conectarse.
- Tu WiFi debe estar como **red privada** (Configuración → Red e Internet → WiFi → tu red → *Red privada*).
- La PC y el celular deben estar en **la misma WiFi**. Algunas redes públicas o de empresas/escuelas aíslan los dispositivos entre sí; ahí no funcionará (en casa o con el hotspot del celular sí).

## Seguridad

- El celular solo entra con la clave que va dentro del QR. *Nueva clave* desconecta a todos los celulares que lo habían escaneado.
- Entre dispositivos con la app, nada se guarda sin que quien recibe toque **Aceptar** (salvo los marcados como de confianza; en una red desconocida mejor no uses esa opción).
- Todo viaja solo por tu red local, no por internet. La conexión no está cifrada (HTTP), así que úsalo en redes de confianza.

## Ejecutar desde el código (opcional)

```
pip install -r requirements.txt
python app.py
```

`python core.py` arranca solo el servidor en modo consola, útil para pruebas.

## Puertos

- TCP **47820**: página del celular y transferencias.
- UDP **47821**: para que las PCs se encuentren entre sí.
