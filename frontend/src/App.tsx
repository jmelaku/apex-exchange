import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import './styles.css'

type Side = 'BUY' | 'SELL'
type OrderType = 'LIMIT' | 'MARKET'
type ConnectionState = 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED'
type OrderTab = 'OPEN' | 'FILLED' | 'CANCELLED' | 'ALL'

type Level = { price_ticks: number; quantity: number; order_count: number }
type Book = { symbol: string; bids: Level[]; asks: Level[] }
type Instrument = { id: number; symbol: string; name: string; tick_size_cents: number; active: boolean }
type Account = { id: number; username: string; available_balance_cents: number; reserved_balance_cents: number }
type Health = { status: string; database: string; matching_engine: string; risk_service: string }
type Order = {
  id: number
  symbol: string
  side: Side
  order_type: OrderType
  quantity: number
  remaining_quantity: number
  price_ticks: number | null
  status: string
  created_at: string
}
type Trade = {
  id: number
  symbol: string
  price_ticks: number
  quantity: number
  buyer_account_id?: number
  seller_account_id?: number
  executed_at: string
}
type Position = {
  id: number
  symbol: string
  quantity: number
  reserved_quantity: number
  available_quantity: number
  average_price_ticks: number
}
type Risk = {
  id: number
  account_id: number
  category: string
  severity: string
  metrics: Record<string, unknown>
  explanation: string
  created_at: string
}
type SubmissionResult = Order & { trades?: Trade[] }
type Feedback = { tone: 'success' | 'error'; title: string; detail?: string }

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const WS = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'
const ACCOUNT_IDS = [1, 2]
const EMPTY_BOOK: Book = { symbol: '', bids: [], asks: [] }

const get = async <T,>(path: string): Promise<T> => {
  const response = await fetch(`${API}${path}`)
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return response.json() as Promise<T>
}

const money = (ticks?: number | null) =>
  ticks == null ? '—' : `$${(ticks / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const cash = (cents?: number | null) =>
  cents == null ? '—' : `$${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const clock = (value?: string) =>
  value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'

const humanStatus = (status: string) => status.toLowerCase().split('_').map((part) => part[0]?.toUpperCase() + part.slice(1)).join(' ')
const humanMetric = (key: string) => key.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
const displayMetric = (value: unknown) => {
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (typeof value === 'string' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

const errorMessage = (payload: unknown): string => {
  if (typeof payload === 'string') return payload
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((item) => (item as { msg?: string }).msg ?? String(item)).join('; ')
  }
  return 'The request could not be completed.'
}

function ServiceBadge({ label, healthy }: { label: string; healthy: boolean }) {
  return <span className={`service-badge ${healthy ? 'healthy' : 'unhealthy'}`}><span className="status-dot" />{label}</span>
}

function Panel({ id, title, eyebrow, action, className = '', children }: { id?: string; title: string; eyebrow?: string; action?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <section id={id} className={`panel ${className}`}>
      <header className="panel-header"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2></div>{action && <div className="panel-action">{action}</div>}</header>
      {children}
    </section>
  )
}

function PriceChart({ symbol, trades }: { symbol: string; trades: Trade[] }) {
  const points = useMemo(() => [...trades].sort((a, b) => +new Date(a.executed_at) - +new Date(b.executed_at)).slice(-40), [trades])
  const chart = useMemo(() => {
    if (points.length < 2) return null
    const prices = points.map((trade) => trade.price_ticks)
    let low = Math.min(...prices)
    let high = Math.max(...prices)
    if (low === high) {
      const padding = Math.max(1, Math.round(low * 0.001))
      low -= padding
      high += padding
    }
    const x = (index: number) => 54 + (index / (points.length - 1)) * 676
    const y = (price: number) => 25 + ((high - price) / (high - low)) * 180
    const line = points.map((trade, index) => `${x(index)},${y(trade.price_ticks)}`).join(' ')
    return { low, high, line, area: `54,205 ${line} 730,205`, x, y }
  }, [points])

  if (!chart) {
    return (
      <div className="chart-empty"><div className="empty-pulse" /><strong>{points.length === 1 ? 'One execution recorded' : `No executed trades for ${symbol}`}</strong><span>At least two real trades are required to draw a price path. APEX never generates synthetic history.</span></div>
    )
  }

  const latest = points[points.length - 1]
  return (
    <div className="chart-wrap">
      <div className="chart-legend"><span><i className="legend-line" /> Execution price</span><strong>{money(latest.price_ticks)}</strong></div>
      <svg className="price-chart" viewBox="0 0 780 245" role="img" aria-label={`${symbol} recent execution price chart`}>
        <defs><linearGradient id="tradeArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#35d2c8" stopOpacity="0.22" /><stop offset="100%" stopColor="#35d2c8" stopOpacity="0" /></linearGradient></defs>
        {[25, 85, 145, 205].map((row) => <line key={row} x1="54" x2="730" y1={row} y2={row} className="chart-gridline" />)}
        <polygon points={chart.area} fill="url(#tradeArea)" />
        <polyline points={chart.line} className="chart-line" />
        <circle cx={chart.x(points.length - 1)} cy={chart.y(latest.price_ticks)} r="4" className="chart-point" />
        <text x="6" y="30" className="chart-label">{money(chart.high)}</text>
        <text x="6" y="208" className="chart-label">{money(chart.low)}</text>
        <text x="54" y="232" className="chart-label">{clock(points[0].executed_at)}</text>
        <text x="730" y="232" textAnchor="end" className="chart-label">{clock(latest.executed_at)}</text>
      </svg>
      <div className="chart-footnote">Last {points.length} persisted executions · selected market only</div>
    </div>
  )
}

function OrderBook({ book }: { book: Book }) {
  const asks = [...book.asks].slice(0, 8).reverse()
  const bids = [...book.bids].slice(0, 8)
  const maxSize = Math.max(1, ...book.asks.map((level) => level.quantity), ...book.bids.map((level) => level.quantity))
  const bestAsk = book.asks[0]?.price_ticks
  const bestBid = book.bids[0]?.price_ticks
  const spread = bestAsk != null && bestBid != null ? bestAsk - bestBid : null
  const rows = (levels: Level[], side: 'ask' | 'bid') => levels.length ? levels.map((level) => {
    const best = level.price_ticks === (side === 'ask' ? bestAsk : bestBid)
    return (
      <div className={`book-row ${side} ${best ? 'best' : ''}`} key={`${side}-${level.price_ticks}`}>
        <span className="depth-bar" style={{ width: `${Math.max(4, (level.quantity / maxSize) * 100)}%` }} />
        <span className="book-price">{money(level.price_ticks)}</span><span>{level.quantity.toLocaleString()}</span><span>{level.order_count}</span>
      </div>
    )
  }) : <div className="book-empty">No {side === 'ask' ? 'asks' : 'bids'}</div>

  return (
    <div className="book">
      <div className="book-side-label ask-label"><span>ASKS</span><small>Lowest offer has priority</small></div>
      <div className="book-columns"><span>Price</span><span>Size</span><span>Orders</span></div>
      <div className="book-levels asks">{rows(asks, 'ask')}</div>
      <div className="spread-row"><span>SPREAD</span><strong>{spread == null ? 'Waiting for both sides' : money(spread)}</strong></div>
      <div className="book-side-label bid-label"><span>BIDS</span><small>Highest bid has priority</small></div>
      <div className="book-columns"><span>Price</span><span>Size</span><span>Orders</span></div>
      <div className="book-levels bids">{rows(bids, 'bid')}</div>
    </div>
  )
}

function OrderTicket({ symbol, accountId, referencePrice, availableCashCents, position, onSubmit, feedback, submitting }: { symbol: string; accountId: number; referencePrice: number | null; availableCashCents: number | null; position?: Position; onSubmit: (payload: { side: Side; order_type: OrderType; quantity: number; price_ticks?: number }) => Promise<void>; feedback: Feedback | null; submitting: boolean }) {
  const [side, setSide] = useState<Side>('BUY')
  const [orderType, setOrderType] = useState<OrderType>('LIMIT')
  const [quantity, setQuantity] = useState('10')
  const [price, setPrice] = useState('')
  useEffect(() => { setPrice('') }, [symbol])
  useEffect(() => { if (!price && referencePrice != null) setPrice((referencePrice / 100).toFixed(2)) }, [referencePrice, price])
  const quantityValue = Number(quantity)
  const priceValue = Number(price)
  const validQuantity = Number.isInteger(quantityValue) && quantityValue > 0
  const validPrice = orderType === 'MARKET' || (Number.isFinite(priceValue) && priceValue > 0)
  const estimate = orderType === 'LIMIT' && validQuantity && validPrice ? quantityValue * priceValue : null
  const orderValueCents = estimate == null ? null : Math.round(estimate * 100)
  const owned = position?.quantity ?? 0
  const reservedShares = position?.reserved_quantity ?? 0
  const availableShares = position?.available_quantity ?? 0
  const exceedsSellCapacity = side === 'SELL' && validQuantity && quantityValue > availableShares
  const exceedsBuyCapacity = side === 'BUY' && orderValueCents != null && availableCashCents != null && orderValueCents > availableCashCents
  const canSubmit = validQuantity && validPrice && !exceedsSellCapacity && !exceedsBuyCapacity && !submitting
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!canSubmit) return
    void onSubmit({ side, order_type: orderType, quantity: quantityValue, ...(orderType === 'LIMIT' ? { price_ticks: Math.round(priceValue * 100) } : {}) })
  }
  return (
    <form className="order-ticket" onSubmit={submit}>
      <div className="ticket-context"><span>ACCOUNT {accountId}</span><strong>{symbol}</strong></div>
      <div className="segmented side-toggle" aria-label="Order side"><button type="button" className={side === 'BUY' ? 'active buy' : ''} onClick={() => setSide('BUY')}>BUY</button><button type="button" className={side === 'SELL' ? 'active sell' : ''} onClick={() => setSide('SELL')}>SELL</button></div>
      <label><span>Order type</span><div className="segmented type-toggle"><button type="button" className={orderType === 'LIMIT' ? 'active' : ''} onClick={() => setOrderType('LIMIT')}>LIMIT</button><button type="button" className={orderType === 'MARKET' ? 'active' : ''} onClick={() => setOrderType('MARKET')}>MARKET</button></div></label>
      <label><span>Quantity {side === 'SELL' && <small className="input-limit">MAX {availableShares.toLocaleString()}</small>}</span><div className="input-shell"><input type="number" min="1" max={side === 'SELL' ? availableShares : undefined} step="1" inputMode="numeric" value={quantity} onChange={(event) => setQuantity(event.target.value)} /><em>SHARES</em></div></label>
      {orderType === 'LIMIT' && <label><span>Limit price</span><div className="input-shell"><b>$</b><input min="0.01" step="0.01" inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} placeholder="0.00" /><em>USD</em></div></label>}
      {side === 'BUY' ? (
        <div className="capacity-card buy-capacity">
          <h3>Buying capacity</h3>
          <div><span>Available cash</span><strong>{cash(availableCashCents)}</strong></div>
          <div><span>Order value</span><strong>{orderValueCents == null ? 'Known after execution' : cash(orderValueCents)}</strong></div>
          <div className="capacity-total"><span>Remaining available cash</span><strong>{orderValueCents == null || availableCashCents == null ? 'Determined after execution' : cash(availableCashCents - orderValueCents)}</strong></div>
        </div>
      ) : (
        <div className="capacity-card sell-capacity">
          <h3>Your {symbol} position</h3>
          <div><span>Owned</span><strong>{owned.toLocaleString()} shares</strong></div>
          <div><span>Reserved to sell</span><strong>{reservedShares.toLocaleString()} shares</strong></div>
          <div className="capacity-total"><span>Available to sell</span><strong>{availableShares.toLocaleString()} shares</strong></div>
        </div>
      )}
      {exceedsSellCapacity && <div className="capacity-warning" role="alert">Only {availableShares.toLocaleString()} {symbol} shares are currently available to sell.</div>}
      {exceedsBuyCapacity && <div className="capacity-warning" role="alert">This limit order exceeds the account's available cash.</div>}
      <div className="order-preview"><span>Order instruction</span><strong>{side} {validQuantity ? quantityValue : '—'} {symbol} @ {orderType === 'MARKET' ? 'MARKET' : validPrice ? money(Math.round(priceValue * 100)) : '—'}</strong><div><span>Estimated value</span><b>{estimate == null ? 'Calculated at execution' : cash(Math.round(estimate * 100))}</b></div></div>
      <button className={`submit-order ${side.toLowerCase()}`} disabled={!canSubmit}>{submitting ? 'SENDING ORDER…' : `${side} ${symbol}`}</button>
      {feedback && <div className={`feedback ${feedback.tone}`} role="status"><strong>{feedback.title}</strong>{feedback.detail && <span>{feedback.detail}</span>}</div>}
      <p className="ticket-note">Orders route to the live C++ matching engine. Market orders do not guarantee an execution price.</p>
    </form>
  )
}

function RecentTrades({ trades, symbol, accountId }: { trades: Trade[]; symbol: string; accountId: number }) {
  const ordered = [...trades].sort((a, b) => +new Date(b.executed_at) - +new Date(a.executed_at)).slice(0, 15)
  const sideFor = (trade: Trade) => trade.buyer_account_id === accountId ? 'BUY' : trade.seller_account_id === accountId ? 'SELL' : null
  return (
    <div className="table-wrap trades-table"><table><thead><tr><th>Time</th><th>Price</th><th>Quantity</th><th>Your side</th></tr></thead><tbody>{ordered.map((trade) => {
      const side = sideFor(trade)
      return <tr key={trade.id}><td className="muted">{clock(trade.executed_at)}</td><td className="numeric strong">{money(trade.price_ticks)}</td><td className="numeric">{trade.quantity.toLocaleString()}</td><td>{side ? <span className={`side-tag ${side.toLowerCase()}`}>{side}</span> : <span className="muted">—</span>}</td></tr>
    })}</tbody></table>{!ordered.length && <div className="table-empty">No trades yet for {symbol}.</div>}</div>
  )
}

function OrdersPanel({ orders, selectedSymbol, onCancel }: { orders: Order[]; selectedSymbol: string; onCancel: (id: number) => void }) {
  const [tab, setTab] = useState<OrderTab>('OPEN')
  const [scope, setScope] = useState<'MARKET' | 'ALL'>('MARKET')
  const isOpen = (order: Order) => ['NEW', 'PARTIALLY_FILLED'].includes(order.status)
  const scoped = scope === 'MARKET' ? orders.filter((order) => order.symbol === selectedSymbol) : orders
  const counts = { OPEN: scoped.filter(isOpen).length, FILLED: scoped.filter((order) => order.status === 'FILLED').length, CANCELLED: scoped.filter((order) => order.status === 'CANCELLED').length, ALL: scoped.length }
  const filtered = scoped.filter((order) => tab === 'ALL' || (tab === 'OPEN' ? isOpen(order) : order.status === tab)).sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))
  return (
    <><div className="orders-controls"><div className="order-tabs" role="tablist">{(['OPEN', 'FILLED', 'CANCELLED', 'ALL'] as OrderTab[]).map((name) => <button key={name} role="tab" aria-selected={tab === name} className={tab === name ? 'active' : ''} onClick={() => setTab(name)}>{name} <span>{counts[name]}</span></button>)}</div><div className="scope-toggle" aria-label="Order market scope"><button className={scope === 'MARKET' ? 'active' : ''} onClick={() => setScope('MARKET')}>{selectedSymbol} ONLY</button><button className={scope === 'ALL' ? 'active' : ''} onClick={() => setScope('ALL')}>ALL MARKETS</button></div></div>
      <div className="table-wrap orders-table"><table><thead><tr><th>ID</th><th>Symbol</th><th>Side</th><th>Type</th><th>Quantity</th><th>Remaining</th><th>Price</th><th>Status</th><th>Time</th><th /></tr></thead><tbody>{filtered.map((order) => <tr key={order.id} className={order.symbol === selectedSymbol ? 'selected-market-row' : ''}><td className="muted">#{order.id}</td><td className="strong">{order.symbol}</td><td><span className={`side-tag ${order.side.toLowerCase()}`}>{order.side}</span></td><td>{order.order_type}</td><td className="numeric">{order.quantity}</td><td className="numeric">{order.remaining_quantity}</td><td className="numeric">{order.order_type === 'MARKET' ? 'MARKET' : money(order.price_ticks)}</td><td><span className={`order-status ${order.status.toLowerCase()}`}>{humanStatus(order.status)}</span></td><td className="muted">{clock(order.created_at)}</td><td>{isOpen(order) && <button className="cancel-button" onClick={() => onCancel(order.id)}>CANCEL</button>}</td></tr>)}</tbody></table>{!filtered.length && <div className="table-empty">No {tab.toLowerCase()} orders for this account.</div>}</div></>
  )
}

function PositionsPanel({ positions, selectedSymbol }: { positions: Position[]; selectedSymbol: string }) {
  return (
    <div className="table-wrap positions-table"><table><thead><tr><th>Symbol</th><th>Owned</th><th>Reserved to sell</th><th>Available to sell</th><th>Average price</th></tr></thead><tbody>{positions.map((position) => <tr key={position.id} className={position.symbol === selectedSymbol ? 'selected-market-row' : ''}><td className="strong">{position.symbol}{position.symbol === selectedSymbol && <span className="current-tag">CURRENT</span>}</td><td className="numeric positive">{position.quantity.toLocaleString()}</td><td className="numeric">{position.reserved_quantity.toLocaleString()}</td><td className="numeric strong">{position.available_quantity.toLocaleString()}</td><td className="numeric">{money(position.average_price_ticks)}</td></tr>)}</tbody></table>{!positions.length && <div className="table-empty">No positions yet. Completed trades will appear here.</div>}<div className="data-note">Owned is settled inventory. Active sell orders reserve their remaining quantity.</div></div>
  )
}

type RiskGroup = Risk & { count: number }
function RiskPanel({ risks }: { risks: Risk[] }) {
  const grouped = useMemo(() => {
    const groups = new Map<string, RiskGroup>()
    for (const risk of [...risks].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))) {
      const key = `${risk.account_id}|${risk.category}|${risk.severity}|${JSON.stringify(risk.metrics)}`
      const existing = groups.get(key)
      if (existing) existing.count += 1
      else groups.set(key, { ...risk, count: 1 })
    }
    return [...groups.values()]
  }, [risks])
  return (
    <div className="risk-content"><div className={`risk-summary ${grouped.length ? 'alerting' : 'normal'}`}><span className="risk-icon">{grouped.length ? '!' : '✓'}</span><div><strong>{grouped.length ? `${grouped.length} RECENT ALERT${grouped.length === 1 ? '' : 'S'}` : 'NORMAL'}</strong><p>{grouped.length ? 'Statistical thresholds detected activity requiring review.' : 'No unusual trading behavior detected.'}</p></div></div>
      <div className="risk-list">{grouped.slice(0, 8).map((risk) => <article className="risk-alert" key={`${risk.id}-${risk.count}`}><div className="risk-alert-head"><span className={`severity ${risk.severity.toLowerCase()}`}>{risk.severity}</span><strong>{risk.category.replaceAll('_', ' ')}</strong>{risk.count > 1 && <span className="duplicate-count">{risk.count} similar</span>}<time>{clock(risk.created_at)}</time></div><div className="risk-account">ACCOUNT {risk.account_id}</div><p>{risk.explanation}</p>{!!Object.keys(risk.metrics ?? {}).length && <div className="risk-metrics">{Object.entries(risk.metrics).slice(0, 4).map(([key, value]) => <span key={key}><small>{humanMetric(key)}</small><b>{displayMetric(value)}</b></span>)}</div>}<details><summary>View detection details</summary><div className="detection-detail"><b>Detection</b><span>Statistical risk engine</span><b>Explanation</b><span>Stored risk-service explanation</span></div></details></article>)}</div>
      <div className="risk-footnote"><b>Detection:</b> statistical risk engine. <b>AI explanation:</b> optional when configured; provider state is not exposed by the API.</div></div>
  )
}

function HowApex({ onClose }: { onClose: () => void }) {
  const steps = [['01', 'Select a market', 'Every market has an independent order book.'], ['02', 'Submit an order', 'Limit orders may rest; market orders seek immediate liquidity.'], ['03', 'C++ engine matches', 'Compatible orders execute using price-time priority.'], ['04', 'PostgreSQL settles', 'Trades, balances, and positions update transactionally.'], ['05', 'WebSockets stream', 'Books, executions, orders, and risk alerts update live.'], ['06', 'Risk service monitors', 'Statistical detectors assess account activity.']]
  return (
    <div className="how-popover" role="dialog" aria-label="How APEX works"><div className="how-title"><div><span className="eyebrow">SYSTEM FLOW</span><h2>How APEX works</h2></div><button onClick={onClose} aria-label="Close">×</button></div><div className="how-steps">{steps.map(([number, title, detail]) => <div key={number}><span>{number}</span><p><strong>{title}</strong><small>{detail}</small></p></div>)}</div></div>
  )
}

function App() {
  const [symbol, setSymbol] = useState('MSFT')
  const [accountId, setAccountId] = useState(1)
  const [instruments, setInstruments] = useState<Instrument[]>([])
  const [book, setBook] = useState<Book>(EMPTY_BOOK)
  const [orders, setOrders] = useState<Order[]>([])
  const [trades, setTrades] = useState<Trade[]>([])
  const [positions, setPositions] = useState<Position[]>([])
  const [risks, setRisks] = useState<Risk[]>([])
  const [account, setAccount] = useState<Account | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [connection, setConnection] = useState<ConnectionState>('CONNECTING')
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [dataError, setDataError] = useState('')
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [showHow, setShowHow] = useState(false)

  useEffect(() => {
    let active = true
    get<Instrument[]>('/instruments').then((data) => {
      if (!active) return
      const activeInstruments = data.filter((instrument) => instrument.active)
      setInstruments(activeInstruments)
      if (activeInstruments.length && !activeInstruments.some((instrument) => instrument.symbol === symbol)) setSymbol(activeInstruments[0].symbol)
    }).catch((error: Error) => setDataError(`Instrument directory unavailable: ${error.message}`))
    return () => { active = false }
  }, [])

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([get<Book>(`/orderbook/${symbol}`), get<Order[]>(`/orders?account_id=${accountId}`), get<Trade[]>(`/trades/${symbol}`), get<Position[]>(`/positions/${accountId}`), get<Risk[]>('/risk-events'), get<Account>(`/accounts/${accountId}`), get<Health>('/health')])
    const [bookResult, ordersResult, tradesResult, positionsResult, risksResult, accountResult, healthResult] = results
    if (bookResult.status === 'fulfilled') setBook(bookResult.value)
    if (ordersResult.status === 'fulfilled') setOrders(ordersResult.value)
    if (tradesResult.status === 'fulfilled') setTrades(tradesResult.value)
    if (positionsResult.status === 'fulfilled') setPositions(positionsResult.value)
    if (risksResult.status === 'fulfilled') setRisks(risksResult.value)
    if (accountResult.status === 'fulfilled') setAccount(accountResult.value)
    if (healthResult.status === 'fulfilled') setHealth(healthResult.value)
    const rejected = results.filter((result) => result.status === 'rejected')
    setDataError(rejected.length ? `${rejected.length} data source${rejected.length === 1 ? '' : 's'} unavailable. Retrying automatically.` : '')
    setUpdatedAt(new Date())
  }, [accountId, symbol])

  useEffect(() => {
    setBook({ ...EMPTY_BOOK, symbol })
    setTrades([])
    void refresh()
    const timer = window.setInterval(() => void refresh(), 20_000)
    return () => window.clearInterval(timer)
  }, [refresh, symbol])

  useEffect(() => {
    let socket: WebSocket | null = null
    let retry: number | undefined
    let refreshTimer: number | undefined
    let stopped = false
    const scheduleRefresh = () => {
      if (refreshTimer) window.clearTimeout(refreshTimer)
      refreshTimer = window.setTimeout(() => void refresh(), 120)
    }
    const connect = () => {
      if (stopped) return
      setConnection('CONNECTING')
      socket = new WebSocket(WS)
      socket.onopen = () => { setConnection('CONNECTED'); socket?.send(JSON.stringify({ subscribe: ['market', 'trades', 'orders', 'risk'] })) }
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as { topic?: string; data?: unknown }
          if (message.topic === 'market') {
            const market = message.data as Book
            if (market.symbol === symbol && Array.isArray(market.bids) && Array.isArray(market.asks)) setBook(market)
          }
          if (['trades', 'orders', 'risk'].includes(message.topic ?? '')) scheduleRefresh()
        } catch { /* Ignore malformed external frames; keep the connection open. */ }
      }
      socket.onclose = () => { setConnection('DISCONNECTED'); if (!stopped) retry = window.setTimeout(connect, 1500) }
      socket.onerror = () => setConnection('DISCONNECTED')
    }
    connect()
    return () => { stopped = true; if (retry) window.clearTimeout(retry); if (refreshTimer) window.clearTimeout(refreshTimer); socket?.close() }
  }, [refresh, symbol])

  const submitOrder = async (payload: { side: Side; order_type: OrderType; quantity: number; price_ticks?: number }) => {
    setSubmitting(true)
    setFeedback(null)
    try {
      const response = await fetch(`${API}/orders`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_id: accountId, symbol, ...payload }) })
      const body = await response.json() as SubmissionResult | unknown
      if (!response.ok) throw new Error(errorMessage(body))
      const order = body as SubmissionResult
      setFeedback({ tone: 'success', title: `Order #${order.id} ${humanStatus(order.status).toLowerCase()}`, detail: order.trades?.length ? `${order.trades.length} execution${order.trades.length === 1 ? '' : 's'} generated.` : 'The order was accepted by the matching engine.' })
      await refresh()
    } catch (error) { setFeedback({ tone: 'error', title: 'Order rejected', detail: error instanceof Error ? error.message : 'Unknown error' }) }
    finally { setSubmitting(false) }
  }

  const cancelOrder = async (id: number) => {
    try {
      const response = await fetch(`${API}/orders/${id}`, { method: 'DELETE' })
      const body = await response.json() as Order | unknown
      if (!response.ok) throw new Error(errorMessage(body))
      setFeedback({ tone: 'success', title: `Order #${id} cancelled`, detail: 'The resting quantity was removed from the book.' })
      await refresh()
    } catch (error) { setFeedback({ tone: 'error', title: `Could not cancel order #${id}`, detail: error instanceof Error ? error.message : 'Unknown error' }) }
  }

  const selectedInstrument = instruments.find((instrument) => instrument.symbol === symbol)
  const selectedPosition = positions.find((position) => position.symbol === symbol)
  const marketBook = book.symbol === symbol ? book : { ...EMPTY_BOOK, symbol }
  const marketTrades = trades.filter((trade) => trade.symbol === symbol)
  const orderedTrades = [...marketTrades].sort((a, b) => +new Date(b.executed_at) - +new Date(a.executed_at))
  const bestBid = marketBook.bids[0]?.price_ticks ?? null
  const bestAsk = marketBook.asks[0]?.price_ticks ?? null
  const lastTrade = orderedTrades[0]?.price_ticks ?? null
  const referencePrice = lastTrade ?? bestAsk ?? bestBid
  const referenceLabel = lastTrade != null ? 'LAST EXECUTION' : bestAsk != null ? 'BEST ASK REFERENCE' : bestBid != null ? 'BEST BID REFERENCE' : 'NO MARKET PRICE'
  const spread = bestBid != null && bestAsk != null ? bestAsk - bestBid : null
  const cashBalance = account ? account.available_balance_cents + account.reserved_balance_cents : null
  const systemHealthy = health?.status === 'healthy' || health?.status === 'ok'

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-group"><div className="apex-mark" aria-label="APEX"><span>A</span></div><div className="brand-copy"><strong>APEX</strong><span>ELECTRONIC EXCHANGE</span></div></div>
        <nav aria-label="Terminal sections"><a href="#markets" className="active">Markets</a><a href="#portfolio">Portfolio</a><a href="#risk">Risk</a></nav>
        <div className="service-strip"><ServiceBadge label={systemHealthy ? 'LIVE' : 'DEGRADED'} healthy={systemHealthy} /><ServiceBadge label={`ENGINE ${health?.matching_engine === 'up' ? 'UP' : 'DOWN'}`} healthy={health?.matching_engine === 'up'} /><ServiceBadge label={`DB ${health?.database === 'up' ? 'UP' : 'DOWN'}`} healthy={health?.database === 'up'} /><ServiceBadge label={`WS ${connection === 'CONNECTED' ? 'LIVE' : connection}`} healthy={connection === 'CONNECTED'} /></div>
        <div className="account-summary"><label>ACCOUNT<select value={accountId} onChange={(event) => setAccountId(Number(event.target.value))}>{ACCOUNT_IDS.map((id) => <option key={id} value={id}>Account {id}</option>)}</select></label><div><span>Cash balance</span><strong>{cash(cashBalance)}</strong></div><div><span>Available</span><strong>{cash(account?.available_balance_cents)}</strong></div><div><span>Reserved</span><strong>{cash(account?.reserved_balance_cents)}</strong></div></div>
      </header>
      {dataError && <div className="data-warning">{dataError}</div>}
      <main>
        <section id="markets" className="market-header">
          <div className="market-picker"><span className="eyebrow">SELECT MARKET</span><select value={symbol} onChange={(event) => setSymbol(event.target.value)} aria-label="Select market">{instruments.map((instrument) => <option key={instrument.id} value={instrument.symbol}>{instrument.symbol} — {instrument.name}</option>)}{!instruments.length && <option value={symbol}>{symbol}</option>}</select></div>
          <div className="market-identity"><div><h1>{symbol}</h1><p>{selectedInstrument?.name ?? 'Simulated instrument'}</p></div><div className="market-price"><strong>{money(referencePrice)}</strong><span>{referenceLabel}</span></div></div>
          <div className="market-stats"><div><span>Best bid</span><strong className="positive">{money(bestBid)}</strong></div><div><span>Best ask</span><strong className="negative">{money(bestAsk)}</strong></div><div><span>Spread</span><strong>{money(spread)}</strong></div><div><span>Last trade</span><strong>{orderedTrades[0] ? clock(orderedTrades[0].executed_at) : '—'}</strong></div></div>
          <div className="symbol-strip" aria-label="Available markets">{instruments.map((instrument) => <button key={instrument.id} className={symbol === instrument.symbol ? 'active' : ''} onClick={() => setSymbol(instrument.symbol)}>{instrument.symbol}</button>)}</div>
        </section>
        <div className="terminal-toolbar"><div><span className="live-line" /> Live exchange events <small>{updatedAt ? `Synced ${clock(updatedAt.toISOString())}` : 'Connecting…'}</small></div><button className="how-button" onClick={() => setShowHow((value) => !value)}>ⓘ HOW APEX WORKS</button>{showHow && <HowApex onClose={() => setShowHow(false)} />}</div>
        <div className="primary-grid">
          <Panel title="Market Visualization" eyebrow={`${symbol} · EXECUTED TRADES`} className="chart-panel" action={<span className="panel-tag">REAL TRADE DATA</span>}><PriceChart symbol={symbol} trades={marketTrades} /></Panel>
          <Panel title="Order Book" eyebrow={`${symbol} · CURRENT BOOK`} className="book-panel" action={<span className="panel-tag">LIVE DEPTH</span>}><OrderBook book={marketBook} /></Panel>
          <Panel title="Recent Trades" eyebrow={`${symbol} · HISTORICAL EXECUTIONS`} className="trades-panel" action={<span className="panel-tag">NEWEST FIRST</span>}><RecentTrades trades={marketTrades} symbol={symbol} accountId={accountId} /></Panel>
          <Panel title="Place Order" eyebrow="ROUTE TO MATCHING ENGINE" className="ticket-panel" action={<span className="panel-tag account">ACCOUNT {accountId}</span>}><OrderTicket symbol={symbol} accountId={accountId} referencePrice={referencePrice} availableCashCents={account?.available_balance_cents ?? null} position={selectedPosition} onSubmit={submitOrder} feedback={feedback} submitting={submitting} /></Panel>
        </div>
        <Panel title="Orders" eyebrow={`ACCOUNT ${accountId} · ORDER HISTORY`} className="orders-panel" action={<span className="panel-tag">{orders.length} ACCOUNT TOTAL</span>}><OrdersPanel orders={orders} selectedSymbol={symbol} onCancel={(id) => void cancelOrder(id)} /></Panel>
        <div className="lower-grid"><Panel id="portfolio" title="Positions" eyebrow={`ACCOUNT ${accountId} · PORTFOLIO`} action={<span className="panel-tag">SETTLED TRADES</span>}><PositionsPanel positions={positions} selectedSymbol={symbol} /></Panel><Panel id="risk" title="AI Risk Monitor" eyebrow="STATISTICAL SURVEILLANCE" action={<span className="panel-tag">{health?.risk_service === 'up' ? 'SERVICE UP' : 'SERVICE DOWN'}</span>}><RiskPanel risks={risks} /></Panel></div>
      </main>
      <footer><span>APEX Exchange · C++20 matching · PostgreSQL settlement · FastAPI gateway</span><span>All prices shown from persisted executions or the current live book.</span></footer>
    </div>
  )
}

export default App
