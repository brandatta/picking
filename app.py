import streamlit as st
import pandas as pd
import mysql.connector
import bcrypt
import random
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # Fallback TZ si CONVERT_TZ no está disponible
import hmac, hashlib, base64
from urllib.parse import urlencode

# ================== CONFIG ==================
st.set_page_config(page_title="VicborDraft", layout="wide")

# ================== HELPERS QUERY PARAMS (compat 1.25+) ==================
def _qp_get() -> dict:
    # Streamlit >= 1.31
    if hasattr(st, "query_params"):
        return st.query_params.to_dict()
    # Fallback: experimental
    try:
        return st.experimental_get_query_params()
    except Exception:
        return {}

def _qp_set(d: dict):
    if hasattr(st, "query_params"):
        st.query_params.from_dict(d)
    else:
        try:
            st.experimental_set_query_params(**d)
        except Exception:
            pass

# ================== NAV EN QUERY PARAMS ==================
def _nav_from_qp():
    """Lee navegación desde la URL (page/pedido)."""
    qp = _qp_get()
    page = qp.get("page")
    if isinstance(page, list): page = page[0]
    pedido = qp.get("pedido")
    if isinstance(pedido, list): pedido = pedido[0]
    try:
        pedido = int(pedido) if pedido not in (None, "", []) else None
    except Exception:
        pedido = None
    return page, pedido

def _nav_to_qp(page: str, pedido: int | None):
    """Escribe navegación a la URL solo si cambió (evita loops)."""
    qp = _qp_get()
    changed = False

    if qp.get("page") != page:
        qp["page"] = page
        changed = True

    target_pedido = None if pedido is None else str(pedido)
    cur_pedido = qp.get("pedido")
    if isinstance(cur_pedido, list):
        cur_pedido = cur_pedido[0]
    if (cur_pedido or None) != target_pedido:
        if target_pedido is None:
            qp.pop("pedido", None)
        else:
            qp["pedido"] = target_pedido
        changed = True

    if changed:
        _qp_set(qp)

# ================== ESTILOS ==================
st.markdown("""
<style>
.block-container { padding-top: 2.5rem !important; }
h1, h2, h3 { margin-top: 0.2rem !important; margin-bottom: 0.8rem !important; line-height: 1.2 !important; white-space: normal !important; }

/* Evita (en lo posible) pull-to-refresh en móvil */
html, body {
  overscroll-behavior-y: none;
  overscroll-behavior-x: contain;
  touch-action: pan-x pan-y;
}
section.main > div { overscroll-behavior: contain; }

/* Tarjetas */
.card {
  border: 1px solid #e9e9e9; border-radius: 12px; padding: 12px 14px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.04); background: #fff; height: 100%;
  overflow: visible;
}
.card h4 { margin: 0 0 6px 0; font-size: 1rem; }
.card small { color: #666; }

/* Columnas sin recortes */
div[data-testid="column"] { overflow: visible !important; }

/* Botones */
div.stButton { width: 100%; display: block; }
div.stButton > button {
  width: 100% !important; box-sizing: border-box !important;
  min-height: 40px; padding: 10px 14px !important;
  display: inline-flex; align-items: center; justify-content: center;
  line-height: 1.1 !important; white-space: nowrap; border-radius: 8px; font-size: 0.95rem;
}
.stButton>button[kind="primary"]   { background-color: #28a745 !important; color: #fff !important; border: 1px solid #28a745 !important; }
.stButton>button[kind="primary"]:hover   { background-color: #218838 !important; border-color: #218838 !important; }
.stButton>button[kind="secondary"] { background-color: #ffffff !important; color: #333 !important; border: 1px solid #d9d9d9 !important; }
.stButton>button[kind="secondary"]:hover { background-color: #f5f5f5 !important; color: #000 !important; border-color: #cfcfcf !important; }

/* Filas */
.detail-row { border-bottom: 1px dashed #ececec; padding: 8px 0; }

/* Línea SKU | Cantidad */
.line { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; }
.line .sku { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.line .qty { min-width: 72px; text-align: right; }

/* Encabezado SKU | Cantidad */
.header-line { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  width: 100%; padding: 6px 0; border-bottom: 1px solid #f0f0f0; font-weight: 600; opacity: .9; }

/* Barra inferior fija */
.confirm-bar { position: sticky; bottom: 0; background: #fafafa; border-top: 1px solid #eee;
  padding: 12px; border-radius: 10px; margin-top: 16px; z-index: 1; }

/* Login */
.login-card { max-width: 420px; margin: 8vh auto; padding: 24px;
  border: 1px solid #eee; border-radius: 12px; background: #fff;
  box-shadow: 0 2px 14px rgba(0,0,0,0.04); }

/* Topbar */
#topbar .stButton > button { white-space: normal !important; min-height: 40px; padding: 10px 12px !important; line-height: 1.2 !important; font-size: 0.95rem; }
#topbar { margin-bottom: .25rem; }
@media (max-width: 900px) { #topbar .stButton > button { font-size: 0.9rem; } }

/* Indicador de pedido con picking confirmado */
.order-dot {
  display: inline-block; width: 10px; height: 10px; border-radius: 50%;
  margin-left: 8px; vertical-align: middle;
}
.order-dot.ok { background: #2ecc71; box-shadow: 0 0 0 2px rgba(46,204,113,.2); }
</style>
""", unsafe_allow_html=True)

# Minimiza pull-to-refresh en el tope (best effort)
st.markdown("""
<script>
(function(){
  let startY = 0;
  window.addEventListener('touchstart', function(e){ startY = e.touches[0].clientY; }, {passive:true});
  window.addEventListener('touchmove', function(e){
    const el = document.scrollingElement || document.documentElement;
    const atTop = el.scrollTop <= 0;
    const goingDown = (e.touches[0].clientY > startY);
    if (atTop && goingDown) { e.preventDefault(); }
  }, {passive:false});
})();
</script>
""", unsafe_allow_html=True)

# ================== CONEXIÓN MYSQL ==================
def get_conn():
    return mysql.connector.connect(
        host=st.secrets["app_marco_new"]["host"],
        user=st.secrets["app_marco_new"]["user"],
        password=st.secrets["app_marco_new"]["password"],
        database=st.secrets["app_marco_new"]["database"],
        port=st.secrets["app_marco_new"].get("port", 3306),
    )

# ================== HELPERS USUARIOS (DB) ==================
def ensure_usuarios_table():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            nombre VARCHAR(100),
            rol VARCHAR(50),
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit(); cur.close(); conn.close()

def count_usuarios():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM usuarios")
    n = cur.fetchone()[0]
    cur.close(); conn.close()
    return n

def create_user(username: str, plain_password: str, nombre: str, rol: str):
    conn = get_conn(); cur = conn.cursor()
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode()
    cur.execute(
        "INSERT INTO usuarios (username, password_hash, nombre, rol) VALUES (%s, %s, %s, %s)",
        (username, hashed, nombre, rol)
    )
    conn.commit(); cur.close(); conn.close()

def list_users():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT username, rol FROM usuarios ORDER BY username")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

def set_password(username: str, new_password: str):
    conn = get_conn(); cur = conn.cursor()
    hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode()
    cur.execute("UPDATE usuarios SET password_hash=%s WHERE username=%s", (hashed, username))
    conn.commit(); cur.close(); conn.close()

def get_user_role():
    u = st.session_state.get("user")
    return (u or {}).get("rol")

def get_username():
    u = st.session_state.get("user")
    return (u or {}).get("username")

# ================== AUTH TOKEN (autologin) ==================
def _auth_secret() -> bytes:
    # Configurá en .streamlit/secrets.toml:
    # APP_AUTH_SECRET = "una-cadena-aleatoria-larga"
    raw = st.secrets.get("APP_AUTH_SECRET", "change-me-please-super-secret")
    return raw.encode("utf-8")

def _sign(msg: str) -> str:
    sig = hmac.new(_auth_secret(), msg.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")

def issue_auth_token(username: str, role: str) -> str:
    ts = str(int(time.time()))
    payload = f"{username}|{role}|{ts}"
    sig = _sign(payload)
    token = f"{payload}|{sig}"
    return base64.urlsafe_b64encode(token.encode()).decode()

def parse_auth_token(token_b64: str):
    try:
        token = base64.urlsafe_b64decode(token_b64.encode()).decode()
        parts = token.split("|")
        if len(parts) != 4:
            return None
        username, role, ts, sig = parts
        payload = f"{username}|{role}|{ts}"
        if hmac.compare_digest(_sign(payload), sig):
            # Expiración (12h). Ajustá si querés.
            if (time.time() - int(ts)) > 12*3600:
                return None
            return {"username": username, "rol": role, "ts": int(ts)}
    except Exception:
        return None
    return None

def set_query_auth(token: str):
    qp = _qp_get()
    qp["auth"] = token
    _qp_set(qp)

def clear_query_auth():
    qp = _qp_get()
    if "auth" in qp:
        del qp["auth"]
    _qp_set(qp)

def get_query_auth() -> str | None:
    qp = _qp_get()
    val = qp.get("auth")
    if isinstance(val, list):
        return val[0]
    return val

# ================== NAV/STATE HELPERS ==================
def go(page: str):
    st.session_state.page = page

def nav_to(page: str, **state):
    """Navega, sincroniza URL (page/pedido) y forza rerun en la misma interacción."""
    for k, v in state.items():
        st.session_state[k] = v
    st.session_state.page = page
    _nav_to_qp(page, st.session_state.get("selected_pedido"))
    st.rerun()

def go_and_sync(page: str):
    """Para on_click simples del topbar sin estado adicional."""
    st.session_state.page = page
    _nav_to_qp(page, st.session_state.get("selected_pedido"))

# ================== AUTH ==================
def validar_usuario(username: str, password: str):
    if not username or not password:
        return None
    conn = get_conn(); cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, username, password_hash, nombre, rol FROM usuarios WHERE username = %s", (username,))
    user = cur.fetchone()
    cur.close(); conn.close()

    if not user:
        return None
    stored = user.get("password_hash")
    if not stored or not isinstance(stored, str) or not stored.startswith("$2"):
        return None
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except ValueError:
        return None
    return user if ok else None

def render_setup_panel():
    if st.secrets.get("SETUP_TOKEN") is None:
        return
    try:
        ensure_usuarios_table()
        if count_usuarios() > 0:
            return
    except:
        pass

    with st.expander("Setup rápido (solo una vez)"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Crear tabla 'usuarios'", use_container_width=True):
                try:
                    ensure_usuarios_table()
                    st.success("Tabla 'usuarios' creada/verificada.")
                except Exception as e:
                    st.error(f"No se pudo crear/verificar la tabla: {e}")
        with col2:
            tok = st.text_input("Token de setup", type="password")
            if st.button("Crear admin por defecto (admin / Admin123!)", type="secondary", use_container_width=True):
                try:
                    ensure_usuarios_table()
                    if tok != st.secrets.get("SETUP_TOKEN"):
                        st.error("Token inválido.")
                    else:
                        conn = get_conn(); cur = conn.cursor()
                        cur.execute("SELECT COUNT(*) FROM usuarios WHERE username=%s", ("admin",))
                        exists = cur.fetchone()[0] > 0
                        cur.close(); conn.close()
                        if exists:
                            st.info("El usuario 'admin' ya existe.")
                        else:
                            create_user("admin", "Admin123!", "Administrador", "admin")
                            st.success("Usuario 'admin' creado. Probá iniciar sesión.")
                except Exception as e:
                    st.error(f"No se pudo crear el admin: {e}")

# ================== ADMIN PANEL: asignación robusta ==================
def bulk_assign_usr_pick(pickers: list[str], mode: str = "all",
                         chunk_size: int = 200, max_retries: int = 3) -> tuple[int, int]:
    if not pickers:
        raise ValueError("La lista de pickers está vacía.")

    conn = get_conn()
    conn.autocommit = True
    cur = conn.cursor()

    try: cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
    except Exception: pass
    try: cur.execute("SET SESSION innodb_lock_wait_timeout = 5")
    except Exception: pass

    if mode == "missing":
        cur.execute("SELECT DISTINCT NUMERO FROM sap WHERE usr_pick IS NULL OR TRIM(usr_pick) = ''")
    else:
        cur.execute("SELECT DISTINCT NUMERO FROM sap")

    numeros = [r[0] for r in cur.fetchall()]
    if not numeros:
        cur.close(); conn.close()
        return (0, 0)

    random.shuffle(numeros)
    pedidos_afectados = 0
    filas_actualizadas = 0

    for i in range(0, len(numeros), chunk_size):
        chunk = numeros[i:i+chunk_size]
        for num in chunk:
            usr = random.choice(pickers)
            for attempt in range(max_retries):
                try:
                    if mode == "missing":
                        cur.execute("""
                            UPDATE sap
                               SET usr_pick = %s
                             WHERE NUMERO = %s
                               AND (usr_pick IS NULL OR TRIM(usr_pick) = '')
                        """, (usr, num))
                    else:
                        cur.execute("""
                            UPDATE sap
                               SET usr_pick = %s
                             WHERE NUMERO = %s
                        """, (usr, num))
                    if cur.rowcount and cur.rowcount > 0:
                        filas_actualizadas += cur.rowcount
                        pedidos_afectados += 1
                    break
                except mysql.connector.errors.DatabaseError as e:
                    if getattr(e, "errno", None) in (1205, 1213):
                        time.sleep(0.4 * (attempt + 1) + random.random() * 0.3)
                        continue
                    else:
                        cur.close(); conn.close()
                        raise

    cur.close(); conn.close()
    return (pedidos_afectados, filas_actualizadas)

# ================== ADMIN USERS PANEL ==================
def render_user_admin_panel():
    u = st.session_state.get("user")
    if not u or u.get("rol") != "admin":
        return

    with st.expander("Administración – Usuarios"):
        tabs = st.tabs(["Crear usuario", "Resetear contraseña", "Asignar pedidos a pickers"])

        with tabs[0]:
            c1, c2 = st.columns(2)
            with c1:
                new_username = st.text_input("Usuario (nuevo)")
                new_nombre   = st.text_input("Nombre")
                new_rol      = st.selectbox("Rol", options=["picker", "operador", "jefe", "admin"], index=0)
            with c2:
                p1 = st.text_input("Contraseña", type="password")
                p2 = st.text_input("Repetir contraseña", type="password")
                st.caption("Sugerido: mínimo 6 caracteres.")
            if st.button("Crear usuario", type="primary", use_container_width=True):
                if not new_username or not p1 or not p2:
                    st.error("Completá usuario y contraseñas.")
                elif p1 != p2:
                    st.error("Las contraseñas no coinciden.")
                elif len(p1) < 6:
                    st.error("La contraseña debe tener al menos 6 caracteres.")
                else:
                    try:
                        conn = get_conn(); cur = conn.cursor()
                        cur.execute("SELECT COUNT(*) FROM usuarios WHERE username=%s", (new_username,))
                        exists = cur.fetchone()[0] > 0
                        cur.close(); conn.close()
                        if exists:
                            st.error(f"El usuario '{new_username}' ya existe.")
                        else:
                            create_user(new_username, p1, new_nombre or new_username, new_rol)
                            st.success(f"Usuario '{new_username}' creado con rol '{new_rol}'.")
                    except Exception as e:
                        st.error(f"No se pudo crear el usuario: {e}")

        with tabs[1]:
            users = list_users()
            if not users:
                st.info("No hay usuarios para mostrar.")
            else:
                usernames = [u for (u, r) in users]
                sel_user = st.selectbox("Usuario", options=usernames)
                np1 = st.text_input("Nueva contraseña", type="password", key="np1")
                np2 = st.text_input("Repetir nueva contraseña", type="password", key="np2")
                if st.button("Resetear contraseña", type="secondary", use_container_width=True):
                    if not np1 or not np2:
                        st.error("Completá ambas contraseñas.")
                    elif np1 != np2:
                        st.error("Las contraseñas no coinciden.")
                    elif len(np1) < 6:
                        st.error("La contraseña debe tener al menos 6 caracteres.")
                    else:
                        try:
                            set_password(sel_user, np1)
                            st.success(f"Contraseña de '{sel_user}' actualizada.")
                        except Exception as e:
                            st.error(f"No se pudo actualizar la contraseña: {e}")

        with tabs[2]:
            st.subheader("Asignación aleatoria de pedidos (usr_pick)")
            txt = st.text_input("Usuarios (separados por coma)", value="usr1, usr2, usr3, usr4")
            pickers = [p.strip() for p in txt.split(",") if p.strip()]
            modo = st.radio("¿Qué pedidos querés afectar?",
                            ["Todos los pedidos (reasignar)", "Solo los que no tienen usr_pick"], index=0)
            mode_key = "all" if modo.startswith("Todos") else "missing"
            if st.button("Asignar ahora", type="primary", use_container_width=True):
                if not pickers:
                    st.error("Ingresá al menos un usuario.")
                else:
                    try:
                        pedidos, filas = bulk_assign_usr_pick(pickers, mode=mode_key)
                        st.success(f"Listo. Asigné {pedidos} pedidos. (Filas afectadas aprox: {filas})")
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"No se pudo completar la asignación: {e}")

# ================== LOGIN ==================
def require_login():
    # Estados base
    if "user" not in st.session_state:
        st.session_state.user = None
    if "page" not in st.session_state:
        st.session_state.page = "list"
    if "selected_pedido" not in st.session_state:
        st.session_state.selected_pedido = None
    if "team_selected_user" not in st.session_state:
        st.session_state.team_selected_user = None

    # --- AUTOLOGIN POR TOKEN EN URL ---
    if st.session_state.user is None:
        tok = get_query_auth()
        if tok:
            data = parse_auth_token(tok)
            if data:
                # verifico que el usuario siga existiendo y recupero sus datos
                try:
                    conn = get_conn(); cur = conn.cursor(dictionary=True)
                    cur.execute(
                        "SELECT id, username, password_hash, nombre, rol FROM usuarios WHERE username=%s",
                        (data["username"],)
                    )
                    u = cur.fetchone()
                    cur.close(); conn.close()
                    if u and u.get("rol") == data.get("rol"):
                        st.session_state.user = u
                except Exception:
                    pass

    # Si ya hay usuario (por token o login normal), mostramos app
    if st.session_state.user is not None:
        # picker no puede quedar en páginas restringidas
        if get_user_role() == "picker" and st.session_state.page in ("team", "team_user"):
            st.session_state.page = "list"

        # Rehidrata navegación desde la URL (soporta refresh / pull-to-refresh)
        page_qp, pedido_qp = _nav_from_qp()
        if page_qp:
            st.session_state.page = page_qp
        if pedido_qp is not None:
            st.session_state.selected_pedido = pedido_qp

        return True

    # --- FLUJO DE LOGIN MANUAL ---
    st.markdown("""
    <style>
    header[data-testid="stHeader"] { display: none; }
    div[data-testid="stToolbar"] { display: none; }
    .block-container { padding-top: 0 !important; }
    .login-card { margin: 4vh auto !important; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="login-card">', unsafe_allow_html=True)
    st.header("Iniciar sesión")
    username = st.text_input("Usuario").strip()
    password = st.text_input("Contraseña", type="password").strip()
    col_l, col_r = st.columns([1,1])
    with col_l:
        login_clicked = st.button("Ingresar", type="primary", use_container_width=True)
    with col_r:
        st.write("")
    st.markdown('</div>', unsafe_allow_html=True)

    try:
        if count_usuarios() == 0 and st.secrets.get("SETUP_TOKEN") is not None:
            render_setup_panel()
    except Exception as e:
        st.error(f"Error verificando usuarios: {e}")

    if login_clicked:
        try:
            ensure_usuarios_table()
        except Exception as e:
            st.error(f"Error preparando tabla de usuarios: {e}")
            return False

        user = validar_usuario(username, password)
        if user:
            st.session_state.user = user
            # emitir token y guardarlo en la URL para autologin tras refresh
            t = issue_auth_token(user["username"], user.get("rol",""))
            set_query_auth(t)
            st.success(f"Bienvenido {user.get('nombre') or user['username']} ({user.get('rol','')})")
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos")
    return False

# ================== DATA ACCESS ==================
@st.cache_data(ttl=30)
def get_orders(buscar: str | None = None,
               current_username: str | None = None,
               current_role: str | None = None) -> pd.DataFrame:
    params = []
    if current_role == "picker":
        base = "SELECT DISTINCT NUMERO, CLIENTE, rs FROM sap WHERE usr_pick = %s"
        params.append(current_username)
        if buscar:
            base += " AND (CAST(NUMERO AS CHAR) LIKE %s OR CLIENTE LIKE %s OR CAST(rs AS CHAR) LIKE %s)"
            params.extend([f"%{buscar}%", f"%{buscar}%", f"%{buscar}%"])
        q = base + " ORDER BY NUMERO DESC LIMIT 150"
    else:
        base = "SELECT DISTINCT NUMERO, CLIENTE, usr_pick, rs FROM sap"
        where = []
        if buscar:
            where.append("(CAST(NUMERO AS CHAR) LIKE %s OR CLIENTE LIKE %s OR CAST(rs AS CHAR) LIKE %s)")
            params.extend([f"%{buscar}%", f"%{buscar}%", f"%{buscar}%"])
        q = base + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY NUMERO DESC LIMIT 150"

    conn = get_conn()
    df = pd.read_sql(q, conn, params=params)
    conn.close()

    if "CLIENTE" in df.columns:
        df["CLIENTE"] = df["CLIENTE"].apply(
            lambda x: str(int(x)) if isinstance(x, (int, float)) and float(x).is_integer() else str(x)
        )
    if "rs" in df.columns:
        df["rs"] = df["rs"].apply(lambda x: "" if x is None else str(x))
    return df

def user_can_open_order(numero: int, current_username: str, current_role: str) -> bool:
    if current_role != "picker":
        return True
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT 1 FROM sap WHERE NUMERO = %s AND usr_pick = %s LIMIT 1", (numero, current_username))
    ok = cur.fetchone() is not None
    cur.close(); conn.close()
    return ok

def get_order_items(numero: int) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql(
        """
        SELECT NUMERO, CLIENTE, CODIGO, ItemName, CANTIDAD, COALESCE(PICKING, 'N') AS PICKING, TS
        FROM sap
        WHERE NUMERO = %s
        ORDER BY CODIGO
        """,
        conn, params=[numero]
    )
    conn.close()

    df["PICKING"] = df["PICKING"].fillna("N").astype(str).str.strip().str.upper().replace({"": "N"})
    if "CLIENTE" in df.columns:
        df["CLIENTE"] = df["CLIENTE"].apply(
            lambda x: str(int(x)) if isinstance(x, (int, float)) and float(x).is_integer() else str(x)
        )
    if "ItemName" in df.columns:
        df["ItemName"] = df["ItemName"].apply(lambda x: "" if x is None else str(x))
    df["CANTIDAD"] = pd.to_numeric(df["CANTIDAD"], errors="coerce").fillna(0)
    df["CANTIDAD"] = df["CANTIDAD"].apply(lambda x: int(x) if float(x).is_integer() else x)
    return df

def update_picking_bulk(numero: int, sku_to_flag: list[tuple[str, str]]):
    if not sku_to_flag:
        return
    conn = get_conn(); cur = conn.cursor()
    cur.executemany(
        "UPDATE sap SET PICKING = %s WHERE NUMERO = %s AND CODIGO = %s",
        [(flag, numero, codigo) for (codigo, flag) in sku_to_flag]
    )
    conn.commit()
    cur.close(); conn.close()

def mark_order_all_items_Y(numero: int):
    """Marca Y en TODOS los ítems del pedido, sella TS en filas sin TS
    y registra el timestamp de confirmación en ts_c."""
    conn = get_conn(); cur = conn.cursor()
    try:
        # 1) Todos los ítems a 'Y'
        cur.execute("UPDATE sap SET PICKING = 'Y' WHERE NUMERO = %s", (numero,))
        # 2) Sella TS solo donde esté NULL
        cur.execute("UPDATE sap SET TS = NOW() WHERE NUMERO = %s AND TS IS NULL", (numero,))
        # 3) Marca timestamp de confirmación del pedido
        #    - Si querés que solo se setee la PRIMERA vez, usá: ... WHERE NUMERO = %s AND TS_C IS NULL
        cur.execute("UPDATE sap SET TS_C = NOW() WHERE NUMERO = %s", (numero,))
        conn.commit()
    finally:
        cur.close(); conn.close()
        
# ======= Progreso por usuario (usr_pick) =======
@st.cache_data(ttl=15)
def get_user_progress() -> pd.DataFrame:
    q = """
    SELECT
      usr_pick AS usuario,
      COUNT(DISTINCT NUMERO) AS pedidos,
      COUNT(*) AS items,
      SUM(CASE WHEN UPPER(COALESCE(PICKING,'N'))='Y' THEN 1 ELSE 0 END) AS items_picked,
      SUM(COALESCE(CAST(CANTIDAD AS DECIMAL(18,4)),0)) AS qty_total,
      SUM(CASE WHEN UPPER(COALESCE(PICKING,'N'))='Y'
               THEN COALESCE(CAST(CANTIDAD AS DECIMAL(18,4)),0) ELSE 0 END) AS qty_picked
    FROM sap
    WHERE TRIM(COALESCE(usr_pick,'')) <> ''
    GROUP BY usr_pick
    ORDER BY usuario
    """
    conn = get_conn()
    df = pd.read_sql(q, conn)
    conn.close()

    df["qty_total"]  = pd.to_numeric(df["qty_total"], errors="coerce").fillna(0)
    df["qty_picked"] = pd.to_numeric(df["qty_picked"], errors="coerce").fillna(0)
    df["pct_qty"] = df.apply(lambda r: int((r["qty_picked"] / r["qty_total"]) * 100) if r["qty_total"] > 0 else 0, axis=1)
    return df

# ======= TS / ETA helpers =======
def get_order_timing(numero: int):
    """
    Devuelve:
      - ts_start: MAX(TS) del pedido (datetime o None)
      - elapsed_min: TIMESTAMPDIFF(MINUTE, MAX(TS), NOW()) (int o None)
      - now_ar: NOW() en America/Argentina/Buenos_Aires (datetime o None)
      - ts_start_ar: MAX(TS) en America/Argentina/Buenos_Aires (datetime o None)
    """
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
              MAX(TS) AS ts_start,
              CASE WHEN MAX(TS) IS NULL
                   THEN NULL
                   ELSE TIMESTAMPDIFF(MINUTE, MAX(TS), NOW())
              END AS elapsed_min,
              CONVERT_TZ(NOW(), @@session.time_zone, 'America/Argentina/Buenos_Aires')   AS now_ar,
              CONVERT_TZ(MAX(TS), @@session.time_zone, 'America/Argentina/Buenos_Aires') AS ts_start_ar
            FROM sap
            WHERE NUMERO = %s
        """, (numero,))
        row = cur.fetchone()
    finally:
        cur.close(); conn.close()

    ts_start    = row[0] if row else None
    elapsed_min = row[1] if row and row[1] is not None else None
    now_ar      = row[2] if row else None
    ts_start_ar = row[3] if row else None
    return ts_start, elapsed_min, now_ar, ts_start_ar

def mysql_now_ba():
    """Devuelve NOW() ya convertido a America/Argentina/Buenos_Aires desde MySQL."""
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT CONVERT_TZ(NOW(), @@session.time_zone, 'America/Argentina/Buenos_Aires')")
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        cur.close(); conn.close()

def ensure_ts_if_started(numero: int):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        SELECT SUM(CASE WHEN UPPER(COALESCE(PICKING,'N'))='Y' THEN 1 ELSE 0 END)
        FROM sap WHERE NUMERO = %s
    """, (numero,))
    cnt_y = cur.fetchone()[0] or 0
    if cnt_y > 0:
        cur.execute("SELECT MIN(TS) FROM sap WHERE NUMERO = %s", (numero,))
        has_ts = cur.fetchone()[0]
        if not has_ts:
            cur.execute("UPDATE sap SET TS = NOW() WHERE NUMERO = %s AND TS IS NULL", (numero,))
            conn.commit()
    cur.close(); conn.close()

def fmt_duration(minutes: float) -> str:
    if minutes <= 0:
        return "0 min"
    m = int(round(minutes))
    h, m = divmod(m, 60)
    return f"{h} h {m} min" if h else f"{m} min"

# ================== LAYOUT: TOP BAR ==================
def render_topbar():
    u = st.session_state.user
    if not u:
        return
    st.markdown('<div id="topbar">', unsafe_allow_html=True)
    c1, csp, c2 = st.columns([3,5,2])
    with c1:
        st.title("VicborDraft")
    with csp:
        if u.get("rol") in ("admin", "jefe"):
            n1, n2 = st.columns(2)
            n1.button("Pedidos", on_click=go_and_sync, args=("list",), use_container_width=True)
            n2.button("Equipo",  on_click=go_and_sync, args=("team",), use_container_width=True)
    with c2:
        if st.button("Cerrar sesión", use_container_width=True):
            # limpiar token de autologin y navegación de la URL
            clear_query_auth()
            _qp_set({})  # limpia page/pedido también

            # limpiar estados
            st.session_state.user = None
            for k in list(st.session_state.keys()):
                if k.startswith("pick_") or k.startswith("btn_pick_"):
                    del st.session_state[k]
                if k in ("team_selected_user", "selected_pedido", "page"):
                    del st.session_state[k]
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# ================== PÁGINA: LISTA ==================
def page_list():
    role = get_user_role()
    uname = get_username()

    st.subheader("Listado de pedidos")
    c1, _ = st.columns([2,1])
    with c1:
        buscar = st.text_input("Buscar por cliente, número o RS", placeholder="Ej: DIA, 100023120 o RS")

    orders_df = get_orders(buscar=buscar, current_username=uname, current_role=role)

    st.markdown("**Resultados**")
    if orders_df.empty:
        if role == "picker":
            st.info("No tenés pedidos asignados (usr_pick).")
        else:
            st.info("No hay pedidos para mostrar.")
        return

    idx, total = 0, len(orders_df)
    while idx < total:
        cols = st.columns([1,1,1])
        for col in cols:
            if idx >= total: break
            row = orders_df.iloc[idx]
            numero, cliente = row.NUMERO, row.CLIENTE
            rs_val = str(row["rs"]) if "rs" in orders_df.columns else ""

            items = get_order_items(numero)
            total_items = len(items)
            picked = (items["PICKING"] == "Y").sum() if total_items > 0 else 0
            pct = int((picked / total_items) * 100) if total_items > 0 else 0

            with col:
                st.markdown('<div class="card">', unsafe_allow_html=True)

                # Título con punto verde si hay al menos un Y
                has_any_y = (items["PICKING"] == "Y").any()
                title_html = f"<h4>Pedido #{numero}"
                if has_any_y:
                    title_html += '<span class="order-dot ok" title="Con picking confirmado"></span>'
                title_html += "</h4>"
                st.markdown(title_html, unsafe_allow_html=True)

                st.markdown(
                    f"<div><small>Cliente:</small> <b>{cliente}</b>"
                    + (f" &nbsp;·&nbsp; <small>RS:</small> <b>{rs_val or '-'}</b>" if "rs" in orders_df.columns else "")
                    + "</div>",
                    unsafe_allow_html=True
                )
                st.progress(pct/100 if total_items>0 else 0.0)
                st.caption(f"Picking: {picked}/{total_items} ({pct}%)")
                # Navegar a detalle con sync URL + rerun inmediato
                if st.button("Ver detalle", key=f"open_{numero}", use_container_width=True):
                    nav_to("detail", selected_pedido=int(numero))
                st.markdown("</div>", unsafe_allow_html=True)
            idx += 1

# ================== PÁGINA: EQUIPO ==================
def render_team_dashboard():
    # Bloqueo para roles no autorizados
    role = get_user_role()
    if role not in ("admin", "jefe"):
        st.warning("No tenés permisos para ver esta sección.")
        go_and_sync("list")
        st.rerun()
        return

    st.subheader("Equipo – Avance por usuario (usr_pick)")
    df = get_user_progress()
    if df.empty:
        st.info("No hay pedidos asignados a usuarios (usr_pick está vacío).")
        return
    filtro = st.text_input("Filtrar usuario", "")
    if filtro:
        df = df[df["usuario"].astype(str).str.contains(filtro, case=False, na=False)]

    idx, total = 0, len(df)
    while idx < total:
        cols = st.columns([1,1,1])
        for col in cols:
            if idx >= total: break
            r = df.iloc[idx]
            usuario = str(r["usuario"])
            pedidos = int(r.get("pedidos", 0) or 0)
            items = int(r.get("items", 0) or 0)
            qty_total = float(r.get("qty_total", 0) or 0)
            qty_picked = float(r.get("qty_picked", 0) or 0)
            pct = int((qty_picked/qty_total)*100) if qty_total > 0 else 0

            with col:
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f"<h4>{usuario}</h4>", unsafe_allow_html=True)
                st.caption(f"Pedidos: {pedidos} · Ítems: {items}")
                st.progress((qty_picked/qty_total) if qty_total > 0 else 0.0)
                st.caption(f"Avance por cantidades: {int(qty_picked)}/{int(qty_total)} ({pct}%)")
                if st.button("Ver pedidos", key=f"ver_{usuario}", use_container_width=True):
                    st.session_state.team_selected_user = usuario
                    go_and_sync("team_user")
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
            idx += 1

# ================== PÁGINA: PEDIDOS DEL USUARIO ==================
def page_team_user_orders():
    # Bloqueo para roles no autorizados
    role = get_user_role()
    if role not in ("admin", "jefe"):
        st.warning("No tenés permisos para ver esta sección.")
        go_and_sync("list")
        st.rerun()
        return

    sel = st.session_state.get("team_selected_user")
    if not sel:
        st.warning("No hay un usuario seleccionado.")
        if st.button("Volver al equipo", use_container_width=True):
            go_and_sync("team"); st.rerun()
        return

    h_left, h_right = st.columns([3,1])
    with h_left:
        st.subheader(f"Pedidos de: {sel}")
    with h_right:
        st.button("← Seleccionar otro usuario", on_click=go_and_sync, args=("team",), use_container_width=True)

    dfp = get_user_progress()
    r = dfp[dfp["usuario"].astype(str).str.lower() == sel.lower()]
    if not r.empty:
        r = r.iloc[0]
        qty_total = float(r.get("qty_total", 0) or 0)
        qty_picked = float(r.get("qty_picked", 0) or 0)
        st.progress((qty_picked/qty_total) if qty_total > 0 else 0.0)
        pct = int((qty_picked/qty_total)*100) if qty_total > 0 else 0
        st.caption(f"Avance por cantidades: {int(qty_picked)}/{int(qty_total)} ({pct}%)")

    buscar = st.text_input("Buscar por cliente, número o RS (solo de este usuario)")
    odf = get_orders(buscar=buscar, current_username=sel, current_role="picker")
    if odf.empty:
        st.info("No hay pedidos para este usuario.")
        c1, c2 = st.columns([1,1])
        with c1:
            st.button("← Volver al equipo", on_click=go_and_sync, args=("team",), use_container_width=True)
        with c2:
            st.button("Ir a Pedidos", on_click=go_and_sync, args=("list",), use_container_width=True)
        return

    i2, t2 = 0, len(odf)
    while i2 < t2:
        cols2 = st.columns([1,1,1])
        for c in cols2:
            if i2 >= t2: break
            row = odf.iloc[i2]
            numero, cliente = row.NUMERO, row.CLIENTE
            rs_val = str(row["rs"]) if "rs" in odf.columns else ""

            items_df = get_order_items(numero)
            total_items = len(items_df)
            picked = (items_df["PICKING"] == "Y").sum() if total_items > 0 else 0
            pct_card = int((picked/total_items)*100) if total_items > 0 else 0

            with c:
                st.markdown('<div class="card">', unsafe_allow_html=True)

                # Título con punto verde si hay al menos un Y
                has_any_y = (items_df["PICKING"] == "Y").any()
                title_html = f"<h4>Pedido #{numero}"
                if has_any_y:
                    title_html += '<span class="order-dot ok" title="Con picking confirmado"></span>'
                title_html += "</h4>"
                st.markdown(title_html, unsafe_allow_html=True)

                st.markdown(
                    f"<div><small>Cliente:</small> <b>{cliente}</b>"
                    + (f" &nbsp;·&nbsp; <small>RS:</small> <b>{rs_val or '-'}</b>" if "rs" in odf.columns else "")
                    + "</div>",
                    unsafe_allow_html=True
                )
                st.progress(pct_card/100 if total_items>0 else 0.0)
                st.caption(f"Picking: {picked}/{total_items} ({pct_card}%)")
                # Navegar a detalle con sync URL + rerun inmediato
                if st.button("Ver detalle", key=f"open_user_{sel}_{numero}", use_container_width=True):
                    nav_to("detail", selected_pedido=int(numero))
                st.markdown("</div>", unsafe_allow_html=True)
            i2 += 1

    c1, c2 = st.columns([1,1])
    with c1:
        st.button("← Volver al equipo", on_click=go_and_sync, args=("team",), use_container_width=True)
    with c2:
        st.button("Ir a Pedidos", on_click=go_and_sync, args=("list",), use_container_width=True)

# ================== PÁGINA: DETALLE ==================
def page_detail():
    numero = st.session_state.selected_pedido
    role = get_user_role()
    uname = get_username()

    if not numero:
        st.warning("No hay pedido seleccionado.")
        if st.button("Volver a pedidos", use_container_width=True):
            nav_to("list", selected_pedido=None)
        return

    if not user_can_open_order(numero, uname, role):
        st.error("No tenés acceso a este pedido (usr_pick no coincide con tu usuario).")
        if st.button("Volver a pedidos", use_container_width=True):
            nav_to("list", selected_pedido=None)
        return

    left, right = st.columns([3,1])
    with left:
        st.title(f"Detalle Pedido #{numero}")
    with right:
        st.write("")
        if st.button("Volver a pedidos", use_container_width=True):
            nav_to("list", selected_pedido=None)
            return

    items_df = get_order_items(numero)
    if items_df.empty:
        st.info("Este pedido no tiene ítems.")
        return

    # Estado inicial por SKU
    for _, r in items_df.iterrows():
        logical_key = f"pick_{numero}_{r['CODIGO']}"
        if logical_key not in st.session_state:
            st.session_state[logical_key] = (str(r["PICKING"]).upper() == "Y")

    # Progreso por cantidades
    total_qty = pd.to_numeric(items_df["CANTIDAD"], errors="coerce").fillna(0).sum()
    picked_qty = sum(
        float(r["CANTIDAD"]) for _, r in items_df.iterrows()
        if st.session_state.get(f"pick_{numero}_{r['CODIGO']}", False)
    )
    pct_qty = int((picked_qty / total_qty) * 100) if total_qty > 0 else 0

    st.progress((picked_qty / total_qty) if total_qty > 0 else 0.0)
    picked_str = str(int(picked_qty)) if float(picked_qty).is_integer() else str(picked_qty)
    total_str  = str(int(total_qty))  if float(total_qty).is_integer()  else str(total_qty)
    st.caption(f"Avance por cantidades: {picked_str} / {total_str} ({pct_qty}%)")

    # ===== ETA (usando reloj de MySQL y fijando inicio de sesión si hace falta) =====
    ts_start, elapsed_min_db, now_ar, ts_start_ar = get_order_timing(numero)

    # Fallbacks si CONVERT_TZ no está disponible
    if now_ar is None:
        try:
            now_ar = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
        except Exception:
            now_ar = datetime.now()

    # Referencia de inicio para ETA: primero la de sesión, si no la de DB
    start_ref_ar = st.session_state.get(f"eta_start_{numero}") or ts_start_ar

    # Recalcular elapsed con datetimes si tengo ambos; si no, usar el de MySQL
    if start_ref_ar is not None and now_ar is not None:
        elapsed_calc_min = max((now_ar - start_ref_ar).total_seconds() / 60.0, 0.0)
    else:
        elapsed_calc_min = elapsed_min_db if elapsed_min_db is not None else None

    if (start_ref_ar is not None) and (picked_qty > 0):
        elapsed_safe = max(float(elapsed_calc_min or 0), 1.0)  # evita /0 y jitter
        remaining_qty = max(float(total_qty) - float(picked_qty), 0.0)
        eta_minutes = (elapsed_safe * remaining_qty) / float(picked_qty) if remaining_qty > 0 else 0.0

        eta_text  = fmt_duration(eta_minutes)
        eta_clock_dt = now_ar + timedelta(minutes=eta_minutes)
        eta_clock = eta_clock_dt.strftime("%H:%M")

        st.caption(f"Tiempo estimado restante: {eta_text} (ETA {eta_clock})")
        st.caption(f"Inicio de picking: {start_ref_ar.strftime('%Y-%m-%d %H:%M:%S') if start_ref_ar else '—'}")
    else:
        st.caption("Tiempo estimado restante: — (se mostrará cuando inicie el picking)")
        if start_ref_ar:
            st.caption(f"Inicio de picking: {start_ref_ar.strftime('%Y-%m-%d %H:%M:%S')}")
        elif ts_start:
            st.caption(f"Inicio de picking: {ts_start.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            st.caption("Inicio de picking: —")

    # Cliente
    cliente = str(items_df["CLIENTE"].iloc[0])
    st.markdown(f"**Cliente:** {cliente}")

    # Encabezado
    c_left, c_right = st.columns([7,3])
    with c_left:
        st.markdown('<div class="header-line"><span>SKU / Descripción</span><span class="qty">Cantidad</span></div>', unsafe_allow_html=True)
    with c_right:
        st.markdown("&nbsp;", unsafe_allow_html=True)

    # Filas (toggle inmediato + set de inicio de sesión + TS en DB al primer verde)
    for i, r in items_df.iterrows():
        logical_key = f"pick_{numero}_{r['CODIGO']}"
        widget_key  = f"btn_{numero}_{r['CODIGO']}_{i}"
        active = st.session_state[logical_key]

        item_name = r.get("ItemName") or ""
        c_left, c_right = st.columns([7,3])
        with c_left:
            sku_txt = str(r["CODIGO"])
            cant = r["CANTIDAD"]
            cant_txt = str(int(cant)) if isinstance(cant, (int, float)) and float(cant).is_integer() else str(cant)
            st.markdown(f'''
                <div class="detail-row">
                  <div class="line">
                    <span class="sku">{sku_txt} – {item_name}</span>
                    <span class="qty">{cant_txt}</span>
                  </div>
                </div>''', unsafe_allow_html=True)
        with c_right:
            btn_type = "primary" if active else "secondary"
            if st.button("Picking", key=widget_key, type=btn_type, use_container_width=True):
                # toggle local
                st.session_state[logical_key] = not active

                # Al pasar a verde por primera vez de la sesión: marco inicio y sello TS en DB
                if not active:
                    try:
                        # 1) Fijo inicio de sesión si no existe
                        if st.session_state.get(f"eta_start_{numero}") is None:
                            st.session_state[f"eta_start_{numero}"] = mysql_now_ba() \
                                or datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
                        # 2) Sello TS en DB si hay nulos
                        conn = get_conn(); cur = conn.cursor()
                        cur.execute("UPDATE sap SET TS = NOW() WHERE NUMERO = %s AND TS IS NULL", (numero,))  # solo pone TS en filas sin TS
                        conn.commit(); cur.close(); conn.close()
                    except Exception:
                        pass

                st.rerun()

    # Confirmar
    st.markdown('<div class="confirm-bar">', unsafe_allow_html=True)
    ccf, _, _ = st.columns([1,1,2])
    with ccf:
        if st.button("Confirmar Picking", key="confirm", use_container_width=True, type="primary"):
            try:
                # Marca Y en TODOS los ítems del pedido y sella TS en filas sin TS
                mark_order_all_items_Y(numero)

                st.success("Picking actualizado (todos los ítems marcados en Y).")
                st.cache_data.clear()
                # Limpiar inicio de ETA de la sesión para este pedido
                st.session_state.pop(f"eta_start_{numero}", None)
                nav_to("list", selected_pedido=None)
            except Exception as e:
                st.error(f"Error al actualizar: {e}")
    st.markdown('</div>', unsafe_allow_html=True)

# ================== APP ==================
if require_login():
    render_topbar()

    if st.session_state.get("user", {}).get("rol") == "admin":
        render_user_admin_panel()

    if st.session_state.page == "list":
        page_list()
    elif st.session_state.page == "team":
        render_team_dashboard()
    elif st.session_state.page == "team_user":
        page_team_user_orders()
    elif st.session_state.page == "detail":
        page_detail()
