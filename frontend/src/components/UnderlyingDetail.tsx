import React from "react";

type Props = {
  underlying: string;
  planType?: string;
  regime?: string;
};

const UnderlyingDetail: React.FC<Props> = ({ underlying, planType, regime }) => {
  if (!underlying) return null;
  return (
    <section style={{ border: "1px dashed #bbb", padding: 12 }}>
      <h4>{underlying} Detail</h4>
      <p>Regime: {regime || "n/a"}</p>
      <p>Plan: {planType || "n/a"}</p>
      <p>Feature and plan details can be expanded in later iterations.</p>
    </section>
  );
};

export default UnderlyingDetail;
