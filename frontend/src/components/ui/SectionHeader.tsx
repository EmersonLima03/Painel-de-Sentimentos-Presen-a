type Props = {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
};

export function SectionHeader({ title, subtitle, actions }: Props) {
  return (
    <div className="section-header">
      <div>
        <h2 className="section-title">{title}</h2>
        {subtitle && <p className="panel-sub">{subtitle}</p>}
      </div>
      {actions && <div className="section-actions">{actions}</div>}
    </div>
  );
}
