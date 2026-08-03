import { useState } from "react";
import "./App.css";
import PriceTargetPage from "./PriceTargetPage";
import MomentumPage from "./MomentumPage";
import EarningsPage from "./EarningsPage";

const TABS = [
  { id: "price-target", label: "Probabilidad de Price Target", Component: PriceTargetPage },
  { id: "momentum", label: "Momentum Post-Evento", Component: MomentumPage },
  { id: "earnings", label: "Reacción a Earnings", Component: EarningsPage },
];

export default function App() {
  const [activeTab, setActiveTab] = useState(TABS[0].id);
  const ActivePage = TABS.find((t) => t.id === activeTab).Component;

  return (
    <div className="page">
      <nav className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={"tab" + (tab.id === activeTab ? " tab-active" : "")}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <ActivePage />
    </div>
  );
}
