import streamlit as st
import pandas as pd
import mysql.connector
import bcrypt
import random   # asignación aleatoria
import time     # backoff en reintentos

# ================== CONFIG ==================
st.set_page_config(page_title="Picking - Pedidos (SAP)", layout="wide")

# ================== ESTILOS ==================
st.markdown("""
<style>
.block-container { padding-top: 2.5rem !important; }

/* Evitar que se corte el título */
h1, h2, h3 {
  margin-top: 0.2rem !important;
  margin-bottom: 0.8rem !important;
  line-height: 1.2 !important;
  white-space: normal !important;
}

/* Tarjetas */
.card {
  border: 1px solid #e9e9e9; border-radius: 12px; padding: 12px 14px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.04); background: #fff; height: 100%;
  overflow: visible; /* <-- FIX: que nada se esconda dentro de la tarjeta */
}
.card h4 { margin: 0 0 6px 0; font-size: 1rem; }
.card small { color: #666; }

/* Columnas sin recortes */
div[data-testid="column"] { overflow: visible !important; }

/* Contenedor del botón y botón a ancho completo + robusto */
div.stButton { width: 100%; display: block; }
div.stButton > button {
  width: 100% !important;
  box-sizing: border-box !important;
  min-height: 40px;
  padding: 10px 14px !important;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1.1 !important;
  white-space: nowrap;
  border-radius: 8px;
}

/* Botones Streamlit: colores según "type" */
.stButton>button[kind="primary"] {
  background-color: #28a745 !important; color: #fff !important; border: 1px solid #28a745 !important;
}
.stButton>button[kind="primary"]:hover { background-color: #218838 !important; border-color: #218838 !important; }
.stButton>button[kind="secondary"] {
  background-color: #ffffff !important; color: #333 !important; border: 1px solid #d9d9d9 !important;
}
.stButton>button[kind="secondary"]:hover {
  background-color: #f5f5f5 !important; color: #000 !important; border-color: #cfcfcf !important;
}

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

/* Caja de login centrada */
.login-card { max-width: 420px; margin: 8vh auto; padding: 24px;
  border: 1px solid #eee; border-radius: 12px; background: #fff;
  box-shadow: 0 2px 14px rgba(0,0,0,0.04); }
</style>
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
    """Devuelve [(username, rol)] ordenados por username."""
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT username, rol FROM usuarios ORDER BY username")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

def set_password(username: str, new_password: str):
    """Resetea la contraseña de un usuario (hash bcrypt)."""
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
    # Mostrar solo si hay SETUP_TOKEN y no hay usuarios
    if st.secrets.get("SETUP_TOKEN") is None:
        return
    try:
        ensure_usuarios_table()
        if count_usuarios() > 0:
            return
    except:
        pass

    with st.expander("🛠️ Setup rápido (solo una vez)"):
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
    """
    Asigna aleatoriamente un usuario de 'pickers' a cada NUMERO de pedido.
    mode: "all" -> reasigna todos los pedidos
          "missing" -> solo pedidos con usr_pick NULL o TRIM(usr_pick)=''
    Actualiza por pedido (uno a uno), con autocommit y reintentos ante 1205/1213.
    Devuelve: (pedidos_afectados, filas_actualizadas_acumuladas)
    """
    if not pickers:
        raise ValueError("La lista de pickers está vacía.")

    conn = get_conn()
    conn.autocommit = True
    cur = conn.cursor()

    try:
        cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
    except Exception:
        pass
    try:
        cur.execute("SET SESSION innodb_lock_wait_timeout = 5")
    except Exception:
        pass

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
    """Panel UI de administración de usuarios (solo admin)."""
    u = st.session_state.get("user")
    if not u or u.get("rol") != "admin":
        return

    with st.expander("⚙️ Administración – Usuarios"):
        tabs = st.tabs(["➕ Crear usuario", "🔁 Resetear contraseña", "🔀 Asignar pedidos a pickers"])

        # --- Crear usuario ---
        with tabs[0]:
            c1, c2 = st.columns(2)
            with c1:
                new_username = st.text_input("Usuario (nuevo)")
                new_nombre   = st.text_input("Nombre")
                new_rol      = st.selectbox("Rol", options=["picker", "operador", "jefe", "admin"], index=0)
            with c2:
                p1 = st.text_input("Contraseña", type="password")
                p2 = st.text_input("Repetir contraseña", type="password")
                st.caption("Sugerido: mínimo 6 caracteres, combiná letras y números.")

            btn = st.button("Crear usuario", type="primary", use_container_width=True)
            if btn:
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

        # --- Resetear contraseña ---
        with tabs[1]:
            users = list_users()
            if not users:
                st.info("No hay usuarios para mostrar.")
            else:
                usernames = [u for (u, r) in users]
                sel_user = st.selectbox("Usuario", options=usernames)
                np1 = st.text_input("Nueva contraseña", type="password", key="np1")
                np2 = st.text_input("Repetir nueva contraseña", type="password", key="np2")
                btn_reset = st.button("Resetear contraseña", type="secondary", use_container_width=True)
                if btn_reset:
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

        # --- Asignar aleatoriamente pedidos ---
        with tabs[2]:
            st.subheader("Asignación aleatoria de pedidos (usr_pick)")
            txt = st.text_input("Usuarios (separados por coma)", value="usr1, usr2, usr3, usr4")
            pickers = [p.strip() for p in txt.split(",") if p.strip()]

            modo = st.radio(
                "¿Qué pedidos querés afectar?",
                ["Todos los pedidos (reasignar)", "Solo los que no tienen usr_pick"],
                index=0
            )
            mode_key = "all" if modo.startswith("Todos") else "missing"

            col_a, col_b = st.columns([1,2])
            with col_a:
                btn_assign = st.button("Asignar ahora", type="primary", use_container_width=True)

            if btn_assign:
                if not pickers:
                    st.error("Ingresá al menos un usuario.")
                else:
                    try:
                        pedidos, filas = bulk_assign_usr_pick(pickers, mode=mode_key)
                        st.success(f"Listo ✅ Asigné {pedidos} pedidos. (Filas afectadas aprox: {filas})")
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"No se pudo completar la asignación: {e}")

# ================== LOGIN ==================
def require_login():
    if "user" not in st.session_state:
        st.session_state.user = None
    if "page" not in st.session_state:
        st.session_state.page = "list"
    if "selected_pedido" not in st.session_state:
        st.session_state.selected_pedido = None
    if "team_selected_user" not in st.session_state:
        st.session_state.team_selected_user = None

    if st.session_state.user is None:
        # Ocultar header/toolbar y reducir padding SOLO en login
        st.markdown("""
        <style>
        header[data-testid="stHeader"] { display: none; }
        div[data-testid="stToolbar"] { display: none; }
        .block-container { padding-top: 0 !important; }
        .login-card { margin: 4vh auto !important; }
        </style>
        """, unsafe_allow_html=True)

        # Pantalla de login
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

        # Setup inicial (si aplica)
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
                st.success(f"Bienvenido {user.get('nombre') or user['username']} ({user.get('rol','')})")
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos")
        return False
    return True

# ================== DATA ACCESS ==================
@st.cache_data(ttl=30)
def get_orders(buscar: str | None = None,
               current_username: str | None = None,
               current_role: str | None = None) -> pd.DataFrame:
    """
    - Admin/operador/jefe: ven todos los pedidos (incluye usr_pick).
    - Picker: solo ve pedidos donde sap.usr_pick = current_username.
    """
    params = []
    if current_role == "picker":
        base = "SELECT DISTINCT NUMERO, CLIENTE FROM sap WHERE usr_pick = %s"
        params.append(current_username)
        if buscar:
            base += " AND (CAST(NUMERO AS CHAR) LIKE %s OR CLIENTE LIKE %s)"
            params.extend([f"%{buscar}%", f"%{buscar}%"])
        q = base + " ORDER BY NUMERO DESC LIMIT 150"
    else:
        base = "SELECT DISTINCT NUMERO, CLIENTE, usr_pick FROM sap"
        where = []
        if buscar:
            where.append("(CAST(NUMERO AS CHAR) LIKE %s OR CLIENTE LIKE %s)")
            params.extend([f"%{buscar}%", f"%{buscar}%"])
        q = base + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY NUMERO DESC LIMIT 150"

    conn = get_conn()
    df = pd.read_sql(q, conn, params=params)
    conn.close()

    if "CLIENTE" in df.columns:
        df["CLIENTE"] = df["CLIENTE"].apply(
            lambda x: str(int(x)) if isinstance(x, (int, float)) and float(x).is_integer() else str(x)
        )
    return df

def user_can_open_order(numero: int, current_username: str, current_role: str) -> bool:
    """Pickers solo pueden abrir pedidos con usr_pick = su usuario. Otros roles (admin/operador/jefe): True."""
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
        SELECT NUMERO, CLIENTE, CODIGO, CANTIDAD, COALESCE(PICKING, 'N') AS PICKING
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

# ======= Progreso por usuario (usr_pick) =======
@st.cache_data(ttl=15)
def get_user_progress() -> pd.DataFrame:
    """
    Devuelve por usuario (usr_pick): pedidos, ítems, ítems pickeados, cantidades totales y pickeadas, y %.
    """
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

# ================== STATE HELPERS ==================
def go(page: str):
    st.session_state.page = page

# ================== LAYOUT: TOP BAR (usuario) ==================
def render_topbar():
    u = st.session_state.user
    if not u:
        return
    c1, csp, c2 = st.columns([3,6,1])
    with c1:
        st.title("Pedidos (SAP)")
    with csp:
        # Navegación para admin/jefe
        if u.get("rol") in ("admin", "jefe"):
            n1, n2 = st.columns(2)
            n1.button("📦 Pedidos", on_click=go, args=("list",), use_container_width=True)
            n2.button("👥 Equipo",   on_click=go, args=("team",), use_container_width=True)
    with c2:
        if st.button("Cerrar sesión", use_container_width=True):
            st.session_state.user = None
            for k in list(st.session_state.keys()):
                if k.startswith("pick_") or k.startswith("btn_pick_"):
                    del st.session_state[k]
            st.rerun()

# ================== PÁGINA: LISTA ==================
def page_list():
    role = get_user_role()
    uname = get_username()

    st.subheader("Listado de pedidos")
    c1, _ = st.columns([2,1])
    with c1:
        buscar = st.text_input("Buscar por cliente o número de pedido", placeholder="Ej: DIA o 100023120")

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

            items = get_order_items(numero)
            total_items = len(items)
            picked = (items["PICKING"] == "Y").sum() if total_items > 0 else 0
            pct = int((picked / total_items) * 100) if total_items > 0 else 0

            with col:
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f"<h4>Pedido #{numero}</h4>", unsafe_allow_html=True)
                st.markdown(f"<div><small>Cliente:</small> <b>{cliente}</b></div>", unsafe_allow_html=True)
                st.progress(pct/100 if total_items>0 else 0.0)
                st.caption(f"Picking: {picked}/{total_items} ({pct}%)")
                if st.button("Ver detalle", key=f"open_{numero}", use_container_width=True):
                    st.session_state.selected_pedido = int(numero)
                    go("detail")
                st.markdown("</div>", unsafe_allow_html=True)
            idx += 1

# ================== PÁGINA: EQUIPO (admin/jefe) ==================
def render_team_dashboard():
    st.subheader("Equipo – Avance por usuario (usr_pick)")

    df = get_user_progress()
    if df.empty:
        st.info("No hay pedidos asignados a usuarios (usr_pick está vacío).")
        return

    # Filtro por usuario
    filtro = st.text_input("Filtrar usuario", "")
    if filtro:
        df = df[df["usuario"].astype(str).str.contains(filtro, case=False, na=False)]

    # Tarjetas por usuario
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
                    go("team_user")
                st.markdown("</div>", unsafe_allow_html=True)
            idx += 1

# ================== PÁGINA: PEDIDOS DEL USUARIO (admin/jefe) ==================
def page_team_user_orders():
    sel = st.session_state.get("team_selected_user")
    if not sel:
        st.warning("No hay un usuario seleccionado.")
        if st.button("Volver al equipo", use_container_width=True):
            go("team")
        return

    st.subheader(f"Pedidos de: {sel}")

    # Muestra progreso del usuario arriba (usando el mismo agregado que en el dashboard)
    dfp = get_user_progress()
    r = dfp[dfp["usuario"].astype(str).str.lower() == sel.lower()]
    if not r.empty:
        r = r.iloc[0]
        qty_total = float(r.get("qty_total", 0) or 0)
        qty_picked = float(r.get("qty_picked", 0) or 0)
        st.progress((qty_picked/qty_total) if qty_total > 0 else 0.0)
        pct = int((qty_picked/qty_total)*100) if qty_total > 0 else 0
        st.caption(f"Avance por cantidades: {int(qty_picked)}/{int(qty_total)} ({pct}%)")

    # Buscador
    buscar = st.text_input("Buscar por cliente o número de pedido (solo de este usuario)")

    # Trae pedidos del usuario como si fuera un picker
    odf = get_orders(buscar=buscar, current_username=sel, current_role="picker")
    if odf.empty:
        st.info("No hay pedidos para este usuario.")
        c1, c2 = st.columns([1,1])
        with c1:
            st.button("← Volver al equipo", on_click=go, args=("team",), use_container_width=True)
        with c2:
            st.button("Ir a Pedidos", on_click=go, args=("list",), use_container_width=True)
        return

    # Tarjetas de pedidos
    i2, t2 = 0, len(odf)
    while i2 < t2:
        cols2 = st.columns([1,1,1])
        for c in cols2:
            if i2 >= t2: break
            row = odf.iloc[i2]
            numero, cliente = row.NUMERO, row.CLIENTE
            items_df = get_order_items(numero)
            total_items = len(items_df)
            picked = (items_df["PICKING"] == "Y").sum() if total_items > 0 else 0
            pct_card = int((picked/total_items)*100) if total_items > 0 else 0

            with c:
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f"<h4>Pedido #{numero}</h4>", unsafe_allow_html=True)
                st.markdown(f"<div><small>Cliente:</small> <b>{cliente}</b></div>", unsafe_allow_html=True)
                st.progress(pct_card/100 if total_items>0 else 0.0)
                st.caption(f"Picking: {picked}/{total_items} ({pct_card}%)")
                if st.button("Ver detalle", key=f"open_user_{sel}_{numero}", use_container_width=True):
                    st.session_state.selected_pedido = int(numero)
                    go("detail")
                st.markdown("</div>", unsafe_allow_html=True)
            i2 += 1

    c1, c2 = st.columns([1,1])
    with c1:
        st.button("← Volver al equipo", on_click=go, args=("team",), use_container_width=True)
    with c2:
        st.button("Ir a Pedidos", on_click=go, args=("list",), use_container_width=True)

# ================== PÁGINA: DETALLE ==================
def page_detail():
    numero = st.session_state.selected_pedido
    role = get_user_role()
    uname = get_username()

    if not numero:
        st.warning("No hay pedido seleccionado.")
        if st.button("Volver a pedidos", use_container_width=True):
            go("list")
        return

    # Seguridad: si es picker, solo puede abrir si usr_pick = su usuario
    if not user_can_open_order(numero, uname, role):
        st.error("No tenés acceso a este pedido (usr_pick no coincide con tu usuario).")
        if st.button("Volver a pedidos", use_container_width=True):
            go("list")
        return

    left, right = st.columns([3,1])
    with left:
        st.title(f"Detalle Pedido #{numero}")
    with right:
        st.write("")
        if st.button("Volver a pedidos", use_container_width=True):
            go("list")
            return

    items_df = get_order_items(numero)
    if items_df.empty:
        st.info("Este pedido no tiene ítems.")
        return

    # Estado inicial por SKU
    for _, r in items_df.iterrows():
        key = f"pick_{numero}_{r['CODIGO']}"
        if key not in st.session_state:
            st.session_state[key] = (r["PICKING"] == "Y")

    # Barra de avance por CANTIDADES
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

    # Cliente
    cliente = str(items_df["CLIENTE"].iloc[0])
    st.markdown(f"**Cliente:** {cliente}")

    # Encabezado alineado
    c_left, c_right = st.columns([7,3])
    with c_left:
        st.markdown('<div class="header-line"><span>SKU</span><span class="qty">Cantidad</span></div>', unsafe_allow_html=True)
    with c_right:
        st.markdown("&nbsp;", unsafe_allow_html=True)

    # Filas de picking
    for _, r in items_df.iterrows():
        key = f"pick_{numero}_{r['CODIGO']}"
        active = st.session_state[key]
        c_left, c_right = st.columns([7,3])
        with c_left:
            sku_txt = str(r["CODIGO"])
            cant = r["CANTIDAD"]
            cant_txt = str(int(cant)) if isinstance(cant, (int, float)) and float(cant).is_integer() else str(cant)
            st.markdown(f'''
                <div class="detail-row">
                  <div class="line">
                    <span class="sku">{sku_txt}</span>
                    <span class="qty">{cant_txt}</span>
                  </div>
                </div>''', unsafe_allow_html=True)
        with c_right:
            btn_type = "primary" if active else "secondary"
            if st.button("Picking", key=f"btn_{key}", type=btn_type, use_container_width=True):
                st.session_state[key] = not active
                st.rerun()

    # Confirmar
    st.markdown('<div class="confirm-bar">', unsafe_allow_html=True)
    ccf, _, _ = st.columns([1,1,2])
    with ccf:
        if st.button("Confirmar cambios", key="confirm", use_container_width=True, type="primary"):
            try:
                updates = []
                for _, r in items_df.iterrows():
                    logical_key = f"pick_{numero}_{r['CODIGO']}"
                    flag = "Y" if st.session_state[logical_key] else "N"
                    updates.append((str(r["CODIGO"]), flag))
                update_picking_bulk(numero, updates)
                st.success("Picking actualizado correctamente.")
                st.cache_data.clear()
                go("list"); st.rerun()
            except Exception as e:
                st.error(f"Error al actualizar: {e}")
    st.markdown('</div>', unsafe_allow_html=True)

# ================== APP ==================
if require_login():
    render_topbar()

    # Panel de administración de usuarios (solo admin)
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
