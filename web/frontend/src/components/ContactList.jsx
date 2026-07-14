export default function ContactList({ contacts, leads, onDelete }) {
  const leadOrdinal = (leadName) => {
    const i = leads.findIndex((l) => l.name === leadName);
    return i >= 0 ? i + 1 : 0;
  };

  const contactNumber = (label) => {
    const m = String(label).match(/\d+/);
    return m ? parseInt(m[0], 10) : Number.POSITIVE_INFINITY;
  };

  if (contacts.length === 0) {
    return (
      <div className="contact-list-empty muted">
        No contacts yet. Click the viewer to place the crosshair, then Submit.
      </div>
    );
  }

  // Display sorted by lead order, then contact number, while keeping each row's
  // original index so deletion still targets the right entry.
  const ordered = contacts
    .map((c, origIdx) => ({ c, origIdx }))
    .sort((a, b) => {
      const lo = leadOrdinal(a.c.lead) - leadOrdinal(b.c.lead);
      if (lo !== 0) return lo;
      if (a.c.lead !== b.c.lead) return a.c.lead < b.c.lead ? -1 : 1;
      return contactNumber(a.c.label) - contactNumber(b.c.label);
    });

  return (
    <ul className="contact-list contact-list-dense">
      {ordered.map(({ c, origIdx }) => {
        const idx = origIdx;
        const lo = leadOrdinal(c.lead);
        const lbl = parseInt(c.label, 10);
        const labelNum = Number.isNaN(lbl) ? c.label : lbl;
        return (
          <li key={`${c.lead}-${c.label}-${idx}`}>
            <span className="contact-line">
              <span className="contact-name">
                {c.lead}
                {c.label}
              </span>
              <span className="contact-indices muted">
                ({lo}, {labelNum})
              </span>
              <span className="coord">
                ({c.coord.R}, {c.coord.A}, {c.coord.S})
                {c.voxel ? (
                  <span className="muted voxel-tag">
                    {" "}
                    vox [{c.voxel[0]}, {c.voxel[1]}, {c.voxel[2]}]
                  </span>
                ) : null}
              </span>
            </span>
            <button
              type="button"
              className="delete-btn"
              onClick={() => onDelete(idx)}
              title="Delete contact"
            >
              ×
            </button>
          </li>
        );
      })}
    </ul>
  );
}
