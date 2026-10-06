import { useEffect, useRef } from "react";
import { basicSetup } from "codemirror";
import { python } from "@codemirror/lang-python";
import { EditorState, Prec, StateEffect, StateField } from "@codemirror/state";
import { Decoration, type DecorationSet, EditorView, keymap } from "@codemirror/view";

const setErrorLine = StateEffect.define<number | null>();

const errorLineField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(decorations, transaction) {
    let next = decorations.map(transaction.changes);
    for (const effect of transaction.effects) {
      if (!effect.is(setErrorLine)) continue;
      const lineNumber = effect.value;
      if (lineNumber === null || lineNumber < 1 || lineNumber > transaction.state.doc.lines) {
        next = Decoration.none;
      } else {
        const line = transaction.state.doc.line(lineNumber);
        next = Decoration.set([Decoration.line({ class: "cm-error-line" }).range(line.from)]);
      }
    }
    return next;
  },
  provide: (field) => EditorView.decorations.from(field),
});

interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** 1-based line to highlight as the failure location. */
  errorLine?: number | null;
  onRun?: () => void;
  placeholder?: string;
}

export function CodeEditor({ value, onChange, errorLine, onRun }: CodeEditorProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const onRunRef = useRef(onRun);
  onChangeRef.current = onChange;
  onRunRef.current = onRun;

  useEffect(() => {
    if (!hostRef.current) return;
    const view = new EditorView({
      parent: hostRef.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          python(),
          errorLineField,
          Prec.highest(
            keymap.of([
              {
                key: "Mod-Enter",
                run: () => {
                  onRunRef.current?.();
                  return true;
                },
              },
            ]),
          ),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) onChangeRef.current(update.state.doc.toString());
          }),
          EditorView.theme({
            "&": { height: "100%", fontSize: "12px" },
            ".cm-scroller": { fontFamily: "var(--font-mono)", lineHeight: "1.55" },
          }),
        ],
      }),
    });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // The editor is created once; later value changes are synced below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const view = viewRef.current;
    if (view && view.state.doc.toString() !== value) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const line = errorLine ?? null;
    const effects: StateEffect<unknown>[] = [setErrorLine.of(line)];
    if (line !== null && line >= 1 && line <= view.state.doc.lines) {
      effects.push(EditorView.scrollIntoView(view.state.doc.line(line).from, { y: "center" }));
    }
    view.dispatch({ effects });
  }, [errorLine, value]);

  return <div className="code-editor" ref={hostRef} />;
}
