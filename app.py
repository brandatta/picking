import streamlit as st
import pandas as pd
import mysql.connector
import bcrypt

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
}
.card h4 { margin: 0 0 6px 0; font-size: 1rem; }
.card small { color: #666; }
.card .stButton>button { width: 100%; border-radius: 8px; padding: 6px 10px; }

/* Botones Streamlit: colores según "type" */
.stButton>button[kind="primary"] {                 /* VERDE (activo) */
  background-color: #28a745 !important;
  color: #fff !important;
  border: 1px solid #28a745 !important;
}
.stButton>button[kind="primary"]:hover {
  background-color: #218838 !important;
  border-color: #218838 !important;
}
.stButton>button[kind="secondary"] {               /* BLANCO (inactivo) */
  background-color: #ffffff !important;
  color: #333 !important;
  border: 1px solid #d9d9d9 !important;
}
.stButton>button[kind="secondary"]:hover {
  background-color: #f5f5f5 !important;
  color: #000 !important;
  border-color: #cfcfcf !important;
}

/* Filas */
.detail-row { border-bottom: 1px dashed #ececec; padding: 8px 0; }

/* Línea SKU | Cantidad */
.line {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  width: 100%;
}
.line .sku { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.line .qty { min-width: 72px; text-align: right; }

/* Encabezado SKU | Cantidad */
.header-line {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  width: 100%; padding: 6px 0; border-bottom: 1px solid #f0f0f0;
  font-weight: 600; opacity: .9;
}

/* Barra inferior fija */
.confirm-bar {
  position: sticky; bottom: 0; background: #fafafa; border-top: 1px solid #eee;
  padding: 12px; border-radius: 10px; margin-top: 16px;
  z-index: 1;
}

/* Caja de login centrada */
.login-card {
  max-width: 420px; margin: 8vh auto; padding: 24px;
  border: 1px solid #eee; border-radius: 12px; background: #fff;
  box-shadow: 0 2px 14px rgba(0,0,0,0.04);
}
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

# ================== AUTH ==================
def validar_usuario(username: str, password: str):
    """
    Devuelve el dict del usuario si las credenciales son válidas, sino None.
    Valida hash bcrypt y evita crashear si el hash guardado es inválido.
    """
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
        # hash mal formado o no bcrypt
        return None

    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except ValueError:
        # e.g., "Invalid salt"
        return None

    return user if ok else None

def render_setup_panel():
    """
    Panel de setup rápido: crear tabla y crear admin por defecto (admin/Admin123!).
    Si existe SETUP_TOKEN en secrets, lo pide; si no, no.
    Aparece solo si no hay usuario logueado (pantalla de login).
    """
    with st.expander("🛠️ Setup rápido (solo una vez)"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Crear tabla 'usuarios'"):
                try:
                    ensure_usuarios_table()
                    st.success("Tabla 'usuarios' creada/verificada.")
                except Exception as e:
                    st.error(f"No se pudo crear/verificar la tabla: {e}")

        with col2:
            need_token = st.secrets.get("SETUP_TOKEN") is not None
            tok = st.text_input("Token (si corresponde)", type="password") if need_token else None

            if st.button("Crear admin por defecto (admin / Admin123!)", type="secondary"):
                try:
                    ensure_usuarios_table()
                    if need_token and tok != st.secrets.get("SETUP_TOKEN"):
                        st.error("Token inválido.")
                    else:
                        # Evitar duplicar admin
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

def require_login():
    if "user" not in st.session_state:
        st.session_state.user = None
    if "page" not in st.session_state:
        st.session_state.page = "list"
    if "selected_pedido" not in st.session_state:
        st.session_state.selected_pedido = None

    if st.session_state.user is None:
        # Pantalla de login
        st.markdown('<div class="login-card">', unsafe_allow_html=True)
        st.header("Iniciar sesión")

        username = st.text_input("Usuario").strip()
        password = st.text_input("Contraseña", type="password").strip()

        col_l, col_r = st.columns([1,1])
        with col_l:
            login_clicked = st.button("Ingresar", type="primary", use_container_width=True)
        with col_r:
            st.write("")  # espacio

        st.markdown('</div>', unsafe_allow_html=True)

        # Panel de setup (crear tabla/crear admin)
        render_setup_panel()

        if login_clicked:
            # Aseguramos que la tabla exista para evitar error si está vacía/recién creada
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
def get_orders(buscar: str | None = None) -> pd.DataFrame:
    base = "SELECT DISTINCT NUMERO, CLIENTE FROM sap"
    where, params = [], []
    if buscar:
        where.append("(CAST(NUMERO AS CHAR) LIKE %s OR CLIENTE LIKE %s)")
        params.extend([f"%{buscar}%", f"%{buscar}%"])
    q = base + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY NUMERO DESC LIMIT 150"
    conn = get_conn()
    df = pd.read_sql(q, conn, params=params)
    conn.close()

    # CLIENTE sin .0 si es entero
    if "CLIENTE" in df.columns:
        df["CLIENTE"] = df["CLIENTE"].apply(
            lambda x: str(int(x)) if isinstance(x, (int, float)) and float(x).is_integer() else str(x)
        )
    return df

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

    # Normalizar PICKING y formatos
    df["PICKING"] = (
        df["PICKING"].fillna("N").astype(str).str.strip().str.upper().replace({"": "N"})
    )
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
    conn = get_conn()
    cur = conn.cursor()
    cur.executemany(
        "UPDATE sap SET PICKING = %s WHERE NUMERO = %s AND CODIGO = %s",
        [(flag, numero, codigo) for (codigo, flag) in sku_to_flag]
    )
    conn.commit()
    cur.close()
    conn.close()

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
    with c2:
        if st.button("Cerrar sesión", use_container_width=True):
            st.session_state.user = None
            # Opcional: limpiar otros estados
            for k in list(st.session_state.keys()):
                if k.startswith("pick_") or k.startswith("btn_pick_"):
                    del st.session_state[k]
            st.rerun()

# ================== PÁGINA: LISTA ==================
def page_list():
    st.subheader("Listado de pedidos")
    c1, _ = st.columns([2,1])
    with c1:
        buscar = st.text_input("Buscar por cliente o número de pedido", placeholder="Ej: DIA o 100023120")
    orders_df = get_orders(buscar=buscar)

    st.markdown("**Resultados**")
    if orders_df.empty:
        st.info("No hay pedidos para mostrar.")
        return

    n_cols, idx, total = 3, 0, len(orders_df)
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
                st.progress(pct/100)
                st.caption(f"Picking: {picked}/{total_items} ({pct}%)")
                if st.button("Ver detalle", key=f"open_{numero}"):
                    st.session_state.selected_pedido = int(numero)
                    go("detail")
                st.markdown("</div>", unsafe_allow_html=True)
            idx += 1

# ================== PÁGINA: DETALLE ==================
def page_detail():
    numero = st.session_state.selected_pedido
    if not numero:
        st.warning("No hay pedido seleccionado.")
        if st.button("Volver a pedidos"):
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

    # Encabezado ALINEADO con las filas (izquierda 7, derecha 3)
    c_left, c_right = st.columns([7,3])
    with c_left:
        st.markdown(
            '<div class="header-line"><span>SKU</span><span class="qty">Cantidad</span></div>',
            unsafe_allow_html=True
        )
    with c_right:
        st.markdown("&nbsp;", unsafe_allow_html=True)

    # Filas (izquierda: SKU|Cantidad; derecha: botón)
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

    # Barra inferior
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
                go("list")
                st.rerun()
            except Exception as e:
                st.error(f"Error al actualizar: {e}")
    st.markdown('</div>', unsafe_allow_html=True)

# ================== APP ==================
if require_login():
    render_topbar()
    if st.session_state.page == "list":
        page_list()
    elif st.session_state.page == "detail":
        page_detail()
