# 🦅 Proyecto Fénix: Sistema de Autorreparación de Infraestructura Cloud

Plataforma resiliente de remediación automática y convergente de infraestructura emulada en **AWS LocalStack** (`http://localhost:4566`), desarrollada en Python para la cátedra de **Programación para la Automatización II (PPA-2 / DEV6)**.

El sistema procesa alertas operacionales externas recibidas mediante **Webhooks HTTP autenticados con HMAC-SHA256**, desacopla la carga de trabajo en colas estándar de **AWS SQS** con política de reentrega a una **Dead Letter Queue (DLQ)**, y ejecuta un **Worker desatendido e idempotente** que remedia recursos cloud (EC2 y S3) usando **Boto3**, actualiza un registro de estado local atómico (`ledger.json`) y despacha notificaciones externas a **Telegram / Slack**.

[Video Defensa del Proyecto](https://ejemplo.com)

---

## 👥 Matriz de Roles y Responsabilidades del Equipo

| Integrante | Rol Técnico | Archivos / Módulos Asignados | Responsabilidad Principal |
| :--- | :--- | :--- | :--- |
| **Integrante 1** | Ingeniero de Entradas, Excepciones y Validación **Rafael Adán Cruz** | `src/fenix/utils/errors.py`<br>`src/fenix/utils/validation.py`<br>`src/fenix/services/events.py` | Jerarquía semántica `FenixError` (herencia estricta de `Exception`), validación regex de identificadores (`^[a-z0-9-]{3,32}$`), marcas ISO 8601 UTC y validación estricta del contrato JSON de eventos. |
| **Integrante 2** | Ingeniero de Mensajería e Inventario Cloud **Mauricio Jesús Goroso Romano** | `src/fenix/config/settings.py`<br>`src/fenix/services/sqs.py`<br>`src/fenix/services/demo.py` | Configuración segura de clientes Boto3 apuntando a LocalStack; creación de cola SQS y DLQ con `RedrivePolicy`; aprovisionamiento de infraestructura mock (`node-01` en EC2 y `bucket-01` en S3) y volcado de `inventory.json`. |
| **Integrante 3** | Ingeniero de Webhooks y Reparación Boto3 **Rodrigo Tarqui Gutierrez** | `src/fenix/utils/crypto.py`<br>`src/fenix/services/receiver.py`<br>`src/fenix/services/remediation.py` (`repair`) | Verificación y firma criptográfica HMAC-SHA256 sobre bytes crudos (`raw_body`) con `hmac.compare_digest()`; receptor FastAPI en `/webhook` (HTTP 202); función convergente de reparación de instancias EC2 y etiquetas S3. |
| **Integrante 4** | Ingeniero de Observabilidad y Comunicación **Javier Alejandro Quiroga** | `src/fenix/utils/logging_json.py`<br>`src/fenix/services/notifications.py` | Pipeline de logging NDJSON no bloqueante (`QueueHandler` y `QueueListener` en RAM) con rotación a 2 MB y compresión Gzip idempotente; conector externo de notificaciones (Telegram / Slack) con manejo de timeouts y backoff ante HTTP 429 (`Retry-After`). |
| **Integrante 5** | Coordinador de Integración y Worker Durable **Noemí Barragan** | `src/fenix/services/worker.py`<br>`src/fenix/services/remediation.py` (`handle`)<br>`src/fenix/cli.py`<br>`src/fenix/utils/state.py` | Bucle de consumo desacoplado con *Long Polling* SQS; actualización atómica del `ledger.json` por etapas; confirmación duradera del mensaje en SQS (`delete_message` / ACK) solo tras reparar y notificar exitosamente; orquestador de interfaz CLI con cumplimiento de PEP 765. |
| **Integrante 6** | Ingeniero de Diagnóstico, Pruebas y Caos **Ezequiel Nahuel Choque Martinez** | `tests/test_fenix.py`<br>`tests/demo/inject_fault.py` | Herramienta CLI de inyección de fallas en LocalStack (`inject_fault.py`); suite automatizada de pruebas forenses y de caos (firmas HMAC inválidas 401, cuerpos malformados 400, contrato inválido 422, fallas de red 503 y derivación a la DLQ con `simulate_failures=5`). |


---



---

## 🛠️ Instalación y Configuración del Entorno

### 1. Clonar el Repositorio
```bash
git clone https://github.com/racoonar-Sla/proyecto_fenix.git
cd fenix_engine
```

### 2. Entorno Virtual Aislado (`.venv`)
* En Windows (PowerShell):
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  ```
* En Linux / macOS:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### 3. Instalar Dependencias y Modo Editable
```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### 4. Variables de Entorno
```powershell
Copy-Item .env.example .env
```

### 5. LocalStack con Docker
```bash
docker compose up -d
```
Verificar que los servicios requeridos (SQS, EC2 mock, S3) respondan en el puerto 4566.


---
