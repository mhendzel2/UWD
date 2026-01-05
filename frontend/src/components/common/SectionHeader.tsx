import React from "react";
import StatusBadge from "./StatusBadge";
import "./SectionHeader.css";

type SectionHeaderProps = {
  title: string;
  eyebrow?: string;
  statusLabel?: string;
  statusTone?: "success" | "warning" | "danger" | "info" | "neutral";
  actions?: React.ReactNode;
  updatedAt?: number;
};

const SectionHeader: React.FC<SectionHeaderProps> = ({ title, eyebrow, statusLabel, statusTone, actions, updatedAt }) => {
  return (
    <div className="sectionHeader">
      <div className="sectionHeaderContent">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h3 className="title">{title}</h3>
        {updatedAt && <div className="timestamp">Updated {new Date(updatedAt).toLocaleTimeString()}</div>}
      </div>
      <div className="sectionHeaderActions">
        {statusLabel && <StatusBadge tone={statusTone} label={statusLabel} subdued />}
        {actions}
      </div>
    </div>
  );
};

export default SectionHeader;
