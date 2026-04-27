# AGENTS

## Fuente de Verdad

Este repo contiene los archivos compartidos del stack `vite-fastapi-sqlite`.

`vite-fastapi-sqlite` es el stack de apps Forger disponible actualmente. Las apps de este stack combinan backend Python/FastAPI, base SQLite local, frontend Vite + React y UI con MUI / Material Design.

Este repo no contiene una app final. Contiene infraestructura común que las apps del stack consumen como submódulo `commons/` o como copia publicada dentro de estructuras de catálogo.

## Rol de Commons

Commons existe para evitar duplicar piezas técnicas comunes entre apps del mismo stack.

Los archivos de este repo deben ser genéricos, reutilizables y sin lógica de negocio específica.

Pertenece a commons:

- Dockerfile base de backend para apps Python/FastAPI con `uv`.
- Dockerfile base de frontend para apps Vite/React.
- helper de base de datos SQLModel/SQLite.
- endpoint compartido de health check.
- helper compartido de CORS.
- cliente HTTP frontend compartido.
- definiciones base de Docker Compose que las apps extienden.

No pertenece a commons:

- modelos de negocio de una app;
- rutas de negocio;
- servicios de dominio;
- pantallas específicas;
- textos de producto;
- categorías, semillas o datos de una app;
- skills específicas de una app;
- scripts operativos propios de una app;
- decisiones visuales que dependan de un producto concreto.

## Contenido Actual

```text
backend/
  Dockerfile        Imagen base del backend con Python y uv
  database.py       Engine SQLModel, init_db y sesiones
  health.py         Router GET /health con validación de base
  cors.py           Lectura de CORS_ORIGINS desde entorno

frontend/
  Dockerfile        Imagen base del frontend con Node/Vite
  client.ts         Cliente HTTP tipado y manejo de errores

docker-compose.base.yml
  Servicios base backend/frontend usados por apps del stack
```

## Contrato Backend

`backend/database.py` define:

- resolución de `DATABASE_URL` desde entorno;
- fallback a una base SQLite local;
- `engine` SQLModel compartido;
- activación de foreign keys en SQLite;
- `init_db()` para crear tablas registradas;
- `get_session()` como dependencia de sesión para FastAPI.

Las apps deben importar sus modelos antes de llamar `init_db()`. La convención del stack usa un archivo local de app para registrar modelos antes de inicializar la base.

`backend/health.py` define:

- router FastAPI compartido;
- endpoint `GET /health`;
- consulta `SELECT 1` contra la base;
- respuesta simple con `status: "ok"` y `database: "sqlite"`.

`backend/cors.py` define:

- helper `allowed_origins()`;
- lectura de `CORS_ORIGINS` desde entorno;
- fallback a orígenes locales de Vite.

## Contrato Frontend

`frontend/client.ts` define:

- `API_BASE_URL` desde `VITE_API_BASE_URL`;
- fallback local a `http://localhost:8000`;
- clase `ApiError`;
- helper genérico `request<T>()`;
- helpers HTTP `get`, `post`, `patch`, `put` y `del`;
- manejo JSON por defecto;
- soporte para `FormData`;
- manejo de errores de red y errores HTTP.

Las apps del stack deben usar este cliente compartido para llamadas HTTP base. Si una app necesita funciones de dominio, debe crear wrappers locales en su propio `frontend/src/api/`.

## Contrato Docker Compose

`docker-compose.base.yml` define servicios base:

- `backend`: construye con `commons/backend/Dockerfile` y ejecuta FastAPI con uvicorn.
- `frontend`: construye con `commons/frontend/Dockerfile` y ejecuta Vite.

Cada app define su propio `docker-compose.yml` y extiende o usa estos servicios según su estructura local.

## Cuándo Editar Commons

Editar commons cuando el cambio cumple todas estas condiciones:

- aplica a más de una app del stack;
- no introduce reglas de negocio;
- mantiene compatibilidad con apps existentes del stack;
- reduce duplicación real;
- mantiene el contrato simple para apps locales;
- puede explicarse como infraestructura del stack, no como feature de una app.

Ejemplos de cambios apropiados:

- mejorar manejo genérico de errores HTTP;
- ajustar configuración base de CORS;
- corregir inicialización SQLite;
- mejorar health check común;
- actualizar Dockerfiles base;
- agregar helpers compartidos mínimos que todas las apps del stack usan.

## Cuándo No Editar Commons

No editar commons cuando el cambio pertenece a una app concreta.

Ejemplos de cambios que deben quedar en una app:

- importar movimientos financieros;
- manejar categorías de Finance OS;
- agregar endpoints de un dominio;
- cambiar tema visual de un producto;
- crear una skill de carga de datos;
- definir permisos de una app;
- ajustar textos de interfaz;
- modificar manifest de una app.

Si una necesidad aparece primero en una sola app, implementarla en esa app. Moverla a commons solo cuando el comportamiento es claramente común al stack y no depende del dominio.

## Relación Con Skeleton y Apps

`skeletons/vite-fastapi-sqlite` usa este repo como base compartida del stack.

Las apps del stack, como `apps/finance-os`, usan commons para infraestructura común y mantienen su lógica propia dentro del repo de la app.

Si se modifica commons, las apps que consumen este repo deben actualizar la referencia de submódulo o copia correspondiente. Ese cambio se versiona dentro del repo de cada app afectada.

## Reglas Para Agentes

- Leer el `AGENTS.md` de la app antes de asumir que un cambio pertenece a commons.
- Mantener commons sin conocimiento de productos específicos.
- No agregar dependencias pesadas sin necesidad compartida clara.
- No cambiar defaults que afecten datos locales sin revisar impacto en apps consumidoras.
- No romper el contrato de `DATABASE_URL`, `CORS_ORIGINS` ni `VITE_API_BASE_URL`.
- No exponer detalles internos de commons al usuario final salvo que pregunte por implementación.
- Describir cambios de commons como mejoras de plataforma o stack, no como capacidades visibles de una app.

## Verificación

Después de cambiar commons, verificar al menos una app consumidora del stack.

Para `finance-os`, las verificaciones relevantes son:

- backend: `scripts/verify.py`;
- frontend: `npm run verify`;
- ejecución local vía Docker Compose cuando el cambio afecta Dockerfiles, mounts o servicios.

Los comandos son herramientas internas del agente. No deben presentarse al usuario final como pasos normales de uso.
