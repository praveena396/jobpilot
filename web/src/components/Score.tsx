import { scoreColor } from "../api";

/** A score ring plus its three components, so a number always shows its parts. */
export function ScoreRing({ score, size = 96 }: { score: number; size?: number }) {
  const r = (size - 10) / 2;
  const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} className={`ring ${scoreColor(score)}`} role="img"
      aria-label={`Match score ${score} out of 100`}>
      <circle cx={size / 2} cy={size / 2} r={r} className="ring-track" />
      <circle cx={size / 2} cy={size / 2} r={r} className="ring-value"
        strokeDasharray={`${(c * score) / 100} ${c}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x="50%" y="50%" className="ring-text" dominantBaseline="central" textAnchor="middle">
        {score}
      </text>
    </svg>
  );
}

export function Bar({ label, value }: { label: string; value: number }) {
  return (
    <div className="bar-row">
      <span className="muted">{label}</span>
      <div className="bar"><div className={scoreColor(value)} style={{ width: `${value}%` }} /></div>
      <span className="bar-val">{value}</span>
    </div>
  );
}
