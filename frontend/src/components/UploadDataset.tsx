import React, { useState } from "react";

type Props = {
  apiBase: string;
  sessionId: string;
  onUploaded: (msg: string) => void;
};

const sources = ["OI_DIFF", "BOT_EOD", "HOT_CHAINS", "DARKPOOL_EOD", "STOCK_SCREENER"];

const UploadDataset: React.FC<Props> = ({ apiBase, sessionId, onUploaded }) => {
  const [source, setSource] = useState<string>(sources[0]);
  const [file, setFile] = useState<File | null>(null);

  const submit = async () => {
    if (!sessionId) {
      alert("Create a session first");
      return;
    }
    if (!file) {
      alert("Pick a CSV file");
      return;
    }
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("file", file);
    const res = await fetch(`${apiBase}/import/${source}`, { method: "POST", body: form });
    if (res.ok) {
      const data = await res.json();
      onUploaded(`Imported ${file.name} (${data.rows} rows)`);
    } else {
      onUploaded("Import failed");
    }
  };

  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>Upload Dataset</h3>
      <label>
        Source
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          {sources.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] || null)} />
      <button onClick={submit}>Upload</button>
    </section>
  );
};

export default UploadDataset;
