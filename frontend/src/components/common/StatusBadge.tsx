import React from "react";
import { StatusTone } from "../../theme";
import styles from "./StatusBadge.module.css";

type StatusBadgeProps = {
  tone?: StatusTone;
  label: string;
  subdued?: boolean;
};

const StatusBadge: React.FC<StatusBadgeProps> = ({ tone = "neutral", label, subdued = false }) => {
  const toneClass = styles[tone] || styles.neutral;
  const badgeClasses = [
    styles.badge,
    toneClass,
    subdued ? styles.subdued : styles.normal,
  ].join(" ");

  return (
    <span className={badgeClasses} aria-label={label}>
      <span className={styles.dot} aria-hidden />
      {label}
    </span>
  );
};

export default StatusBadge;
