import { useState } from "react";
import { AppSidebar } from "./features/studio/components/AppSidebar";
import { BriefForm } from "./features/studio/components/BriefForm";
import { DraftPanel } from "./features/studio/components/DraftPanel";
import type { BriefInput } from "./features/studio/types";

function App() {
  const [previewBrief, setPreviewBrief] = useState<BriefInput | null>(null);

  return (
    <main className="app-shell">
      <AppSidebar onNewSession={() => setPreviewBrief(null)} />
      <div className="workspace">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">AI CREATIVE STUDIO</p>
            <h1>어떤 광고를 만들어볼까요?</h1>
          </div>
          <span className="scaffold-badge">UI SCAFFOLD</span>
        </header>
        <div className="workspace-grid">
          <BriefForm onPreview={setPreviewBrief} />
          <DraftPanel brief={previewBrief} />
        </div>
      </div>
    </main>
  );
}

export default App;
