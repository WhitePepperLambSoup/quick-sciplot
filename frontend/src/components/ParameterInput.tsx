import { useEffect, useState } from "react";
import type { CodeParameter } from "../types";

export type Language = "zh" | "en";

interface ParameterInputProps {
  parameter: CodeParameter;
  disabled: boolean;
  onApply: (parameter: CodeParameter, value: string) => Promise<void>;
  language: Language;
}

export function ParameterInput({ parameter, disabled, onApply, language }: ParameterInputProps) {
  const [value, setValue] = useState(parameter.value);

  useEffect(() => {
    setValue(parameter.value);
  }, [parameter.value]);

  const commit = (valToCommit?: string) => {
    const finalVal = valToCommit !== undefined ? valToCommit : value;
    if (!disabled && finalVal !== parameter.value) {
      void onApply(parameter, finalVal);
    }
  };

  const isColumn = (parameter.type === "column" || parameter.type === "column_name") && parameter.options?.length;
  const isColor =
    parameter.name.toLowerCase().includes("color") ||
    /^#[0-9a-fA-F]{6}$/.test(value.trim());
  const isAlpha =
    parameter.name.toLowerCase().includes("alpha") ||
    (parameter.type === "number" && Number(parameter.value) >= 0 && Number(parameter.value) <= 1 && parameter.name.toLowerCase().includes("opacity"));

  return (
    <label className="parameter-field">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>{language === "en" ? parameter.name : parameter.label}</span>
        <span style={{ fontSize: "9px", color: "var(--text-muted)" }}>L{parameter.start_line}</span>
      </div>

      {isColumn ? (
        <select
          value={value}
          disabled={disabled}
          title={`源码位置 L${parameter.start_line}`}
          onChange={(e) => {
            setValue(e.target.value);
            void onApply(parameter, e.target.value);
          }}
        >
          {parameter.options?.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : isColor ? (
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <input
            type="color"
            value={/^#[0-9a-fA-F]{6}$/.test(value.trim()) ? value.trim() : "#2563eb"}
            disabled={disabled}
            style={{ width: "26px", height: "26px", padding: "1px", border: "1px solid var(--border-default)", borderRadius: "4px", cursor: "pointer", background: "none" }}
            onChange={(e) => {
              setValue(e.target.value);
              commit(e.target.value);
            }}
            title="点击打开调色板选取颜色"
          />
          <input
            type="text"
            value={value}
            disabled={disabled}
            style={{ flex: 1 }}
            title={`源码位置 L${parameter.start_line}`}
            onChange={(e) => setValue(e.target.value)}
            onBlur={() => commit()}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
            }}
          />
        </div>
      ) : isAlpha ? (
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={isNaN(Number(value)) ? 1 : Number(value)}
            disabled={disabled}
            style={{ flex: 1, accentColor: "var(--primary-500)" }}
            onChange={(e) => {
              setValue(e.target.value);
            }}
            onMouseUp={() => commit()}
            onTouchEnd={() => commit()}
          />
          <span style={{ fontSize: "11px", minWidth: "28px", textAlign: "right", fontFamily: "var(--font-mono)" }}>
            {isNaN(Number(value)) ? value : Number(value).toFixed(2)}
          </span>
        </div>
      ) : (
        <input
          type={parameter.type === "number" ? "number" : "text"}
          value={value}
          disabled={disabled}
          title={`源码位置 L${parameter.start_line}`}
          onChange={(e) => setValue(e.target.value)}
          onBlur={() => commit()}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
          }}
        />
      )}
    </label>
  );
}
