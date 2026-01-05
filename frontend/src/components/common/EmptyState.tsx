import React from "react";
import "./EmptyState.css";

type EmptyStateProps = {
  title: string;
  description?: string;
  action?: React.ReactNode;
};

const EmptyState: React.FC<EmptyStateProps> = ({ title, description, action }) => (
  <div className="emptyState">
    <h4 className="emptyStateTitle">{title}</h4>
    {description && <p className="emptyStateDescription">{description}</p>}
    {action && <div className="emptyStateAction">{action}</div>}
  </div>
);

export default EmptyState;
