-- =====================================================
-- Blumenau Automação - E-commerce Schema (Cloudflare D1)
-- =====================================================

-- Tabela de Produtos (sincronizada com products.json)
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    brand TEXT,
    price REAL NOT NULL DEFAULT 0,
    price_formatted TEXT,
    stock INTEGER,
    in_stock INTEGER DEFAULT 1,  -- 1 = true, 0 = false
    description TEXT,
    category TEXT,
    category_path TEXT,  -- JSON array as string
    image TEXT,
    images TEXT,  -- JSON array as string
    datasheet TEXT,
    source_url TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Índices para produtos
CREATE INDEX IF NOT EXISTS idx_products_slug ON products(slug);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_in_stock ON products(in_stock);

-- Tabela de Clientes
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    phone TEXT,
    cpf TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email);

-- Tabela de Endereços
CREATE TABLE IF NOT EXISTS addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    street TEXT NOT NULL,
    number TEXT NOT NULL,
    complement TEXT,
    neighborhood TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    zip_code TEXT NOT NULL,
    is_default INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_addresses_customer ON addresses(customer_id);

-- Tabela de Pedidos
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_reference TEXT UNIQUE NOT NULL,  -- UUID para referência externa
    customer_id INTEGER,

    -- Dados do cliente (snapshot no momento do pedido)
    customer_name TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    customer_phone TEXT,
    customer_cpf TEXT,

    -- Endereço de entrega (snapshot)
    shipping_street TEXT,
    shipping_number TEXT,
    shipping_complement TEXT,
    shipping_neighborhood TEXT,
    shipping_city TEXT,
    shipping_state TEXT,
    shipping_zip_code TEXT,

    -- Valores
    subtotal REAL NOT NULL DEFAULT 0,
    shipping_cost REAL DEFAULT 0,
    discount REAL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,

    -- Status do pedido
    status TEXT NOT NULL DEFAULT 'pending',
    -- Valores: pending, approved, in_process, rejected, cancelled, refunded

    -- Mercado Pago
    mp_payment_id TEXT,
    mp_preference_id TEXT,
    mp_status TEXT,
    mp_status_detail TEXT,
    mp_payment_type TEXT,  -- credit_card, pix, boleto, etc.

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    paid_at TEXT,

    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE INDEX IF NOT EXISTS idx_orders_external_reference ON orders(external_reference);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_mp_payment_id ON orders(mp_payment_id);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);

-- Tabela de Itens do Pedido
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id TEXT NOT NULL,

    -- Snapshot do produto no momento da compra
    product_name TEXT NOT NULL,
    product_sku TEXT,
    product_image TEXT,

    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL,
    total_price REAL NOT NULL,

    created_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id);

-- Tabela de Log de Webhooks (para debug e auditoria)
CREATE TABLE IF NOT EXISTS webhook_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,  -- mercadopago, etc.
    event_type TEXT,
    payload TEXT,  -- JSON completo
    processed INTEGER DEFAULT 0,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_webhook_logs_source ON webhook_logs(source);
CREATE INDEX IF NOT EXISTS idx_webhook_logs_created_at ON webhook_logs(created_at);

-- View para relatório de vendas
CREATE VIEW IF NOT EXISTS v_sales_report AS
SELECT
    DATE(o.created_at) as date,
    COUNT(DISTINCT o.id) as total_orders,
    SUM(o.total) as total_revenue,
    COUNT(DISTINCT o.customer_email) as unique_customers,
    SUM(oi.quantity) as total_items_sold
FROM orders o
LEFT JOIN order_items oi ON o.id = oi.order_id
WHERE o.status = 'approved'
GROUP BY DATE(o.created_at)
ORDER BY date DESC;
