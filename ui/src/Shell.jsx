/**
 * The console chrome: icon rail, topbar, breadcrumbs, footer.
 *
 * Every rail entry except Interview Training is disabled. This service is one
 * product inside the SkillBrew.AI console; showing the neighbours as live links
 * would promise navigation that goes nowhere.
 */

const RAIL = [
  {
    key: 'home',
    title: 'Home',
    path: <path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" />,
  },
  {
    key: 'brewvoice',
    title: 'BrewVoice',
    path: <path d="M4 14v-2a8 8 0 0 1 16 0v2M4 14h3v5H4zM17 14h3v5h-3z" />,
  },
  {
    key: 'ai-interviews',
    title: 'AI Interviews',
    path: (
      <>
        <rect x="3" y="5" width="18" height="12" rx="2" />
        <path d="M8 21h8" />
      </>
    ),
  },
  {
    key: 'training',
    title: 'Interview Training',
    active: true,
    path: (
      <>
        <path d="M12 3l9 4-9 4-9-4z" />
        <path d="M5 10v5c0 1.5 3 3 7 3s7-1.5 7-3v-5" />
      </>
    ),
  },
  {
    key: 'assessments',
    title: 'Assessments',
    path: <path d="M9 5h6M9 12h6M9 19h6M5 5h.01M5 12h.01M5 19h.01" />,
  },
]

function RailIcon({ item }) {
  return (
    <button
      className={`ri ${item.active ? 'active' : ''}`}
      title={item.active ? item.title : `${item.title} — not part of this service`}
      disabled={!item.active}
      type="button"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        {item.path}
      </svg>
    </button>
  )
}

/**
 * @param crumbs [{label, onClick?}] — the last entry renders as the current page.
 */
export default function Shell({ crumbs = [], children }) {
  return (
    <div className="app">
      <aside className="rail" aria-label="Navigation">
        <svg className="logo" viewBox="0 0 32 32" fill="none">
          <path
            d="M16 3v26M9 9c0 5 14 5 14 0M9 23c0-5 14-5 14 0"
            stroke="#0555C8"
            strokeWidth="2.4"
            strokeLinecap="round"
          />
        </svg>
        {RAIL.map((item) => (
          <RailIcon key={item.key} item={item} />
        ))}
        <div className="spacer" />
      </aside>

      <div className="main">
        <div className="topbar">
          <div className="muted">SkillBrew.AI</div>
          <div className="tb-r">
            <span className="avatar">S</span>
          </div>
        </div>

        <div className="content">
          {crumbs.length > 0 && (
            <div className="crumbs">
              {crumbs.map((c, i) => (
                <span key={c.label}>
                  {i > 0 && <span style={{ margin: '0 8px' }}>›</span>}
                  <span
                    className={i === crumbs.length - 1 ? 'cur' : c.onClick ? 'nav' : ''}
                    onClick={i === crumbs.length - 1 ? undefined : c.onClick}
                  >
                    {c.label}
                  </span>
                </span>
              ))}
            </div>
          )}
          {children}
        </div>

        <div className="footer">
          <span>© 2026 Skillbru AI Pvt Ltd</span>
          <span>Terms</span>
          <span>Privacy</span>
          <span>Contact</span>
        </div>
      </div>
    </div>
  )
}
