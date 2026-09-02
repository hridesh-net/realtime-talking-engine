/**
 * The console chrome: icon rail, topbar, breadcrumbs, footer.
 *
 * The rail carries **only Interview Training** — the one product this service
 * is. It used to carry four more (Home, BrewVoice, AI Interviews, Assessments),
 * every one of them `disabled` with a "not part of this service" tooltip, on
 * the theory that the neighbours should be visible even if unreachable. In
 * practice a column of dead icons reads as a broken console rather than a
 * bigger one, so they are gone. Add an entry here only when it navigates.
 */

const RAIL = [
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
]

function RailIcon({ item }) {
  return (
    <button className={`ri ${item.active ? 'active' : ''}`} title={item.title} type="button">
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
        <img className="logo" src="/logo.svg" alt="SkillBrew" />
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
