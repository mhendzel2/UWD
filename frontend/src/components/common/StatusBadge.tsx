import React from "react";
import { StatusTone } from "../../theme";
import "./StatusBadge.css";

type StatusBadgeProps = {
  tone?: StatusTone;
  label: string;
  subdued?: boolean;
};

const StatusBadge: React.FC<StatusBadgeProps> = ({ tone = "neutral", label, subdued = false }) => {
  const badgeClasses = ["statusBadge", tone, subdued && "subdued"].filter(Boolean).join(" ");
  const indicatorClasses = ["statusIndicator", tone].join(" ");

  return (
    <span className={badgeClasses} aria-label={label}>
      <span aria-hidden className={indicatorClasses} />
      {label}
    </span>
  );
};

export default StatusBadge;
