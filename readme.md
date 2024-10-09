
# Sistema de Gestión de Videos ONVIF

## Descripción
Este proyecto es un sistema de gestión de videos ONVIF desarrollado con Flask. Permite a los usuarios administrar, visualizar y grabar videos de cámaras ONVIF, con una interfaz web intuitiva y funciones de autenticación.

## Características
- 🎥 Visualización de videos de cámaras ONVIF
- 📹 Grabación de video en tiempo real
- 🖼️ Generación automática de vistas previas
- 🔐 Sistema de autenticación de usuarios
- 📁 Gestión de archivos de video (renombrar, eliminar, descargar)
- 🔄 Actualización automática del dashboard
- 📱 Interfaz responsive para dispositivos móviles y de escritorio

## Requisitos
- Python 3.10+
- Flask
- OpenCV
- Otras dependencias listadas en `requirements.txt`

## Instalación
1. Clona este repositorio:
   ```
   git clone https://github.com/hircoir/python-onvif-client.git
   ```
2. Navega al directorio del proyecto:
   ```
   cd python-onvif-client
   ```
3. Instala las dependencias:
   ```
   pip install -r requirements.txt
   ```

## Configuración
1. Edita el archivo `config.py` y configura las variables según tu entorno:
   - `DIRECTORIO_VIDEOS`: Ruta donde se almacenarán los videos
   - `USUARIOS`: Diccionario de usuarios y contraseñas para la autenticación

2. Para agregar o editar usuarios del panel, modifica el diccionario `USUARIOS` en `config.py`:
   ```python
   USUARIOS = {
       'admin': 'password123',
       'usuario1': 'clave456',
       'nuevo_usuario': 'nueva_contraseña'
   }
   ```
   Añade nuevos pares de usuario:contraseña o modifica los existentes según sea necesario.

## Uso
1. Inicia la aplicación:
   ```
   python app.py
   ```
2. Abre un navegador y visita `http://localhost:5000`
3. Inicia sesión con las credenciales configuradas en `config.py`


## Licencia
Distribuido bajo la Licencia MIT. Ver `LICENSE` para más información.


Link del Proyecto: [https://github.com/hircoir/python-onvif-client](https://github.com/hircoir/python-onvif-client)

## Usado
- [Flask](https://flask.palletsprojects.com/)
- [OpenCV](https://opencv.org/)
- [Tailwind CSS](https://tailwindcss.com/)
