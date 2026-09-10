import { memo, useId, useMemo } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import styles from "./markdown.module.css";

const createComponents = (prefix: string): Components => ({
  // Message headings sit below the room title, regardless of the model's heading level.
  h1: ({ children, id }) => <h3 id={id}>{children}</h3>,
  h2: ({ children, id }) => <h3 id={id === "footnote-label" ? `${prefix}label` : id}>{children}</h3>,
  a: ({ href, children, ...props }) => href ? (
    <a href={href} target={href.startsWith("#") ? undefined : "_blank"}
      rel="noopener noreferrer" aria-label={props["aria-label"]}
      aria-describedby={props["aria-describedby"] === "footnote-label" ? `${prefix}label` : props["aria-describedby"]}
      id={props.id}>{children}</a>
  ) : <span>{children}</span>,
  // Model prose is text; an image must not trigger a remote request in a saved transcript.
  img: ({ alt }) => <span className={styles.imageAlt}>{alt}</span>,
  table: ({ children }) => <div className={styles.tableScroll} role="region" aria-label="대화 속 표" tabIndex={0}>
    <table>{children}</table>
  </div>,
  pre: ({ children }) => <pre tabIndex={0} role="region" aria-label="코드">{children}</pre>,
});

/** Only ordinary, already-public message text reaches this renderer. */
export const ConversationMarkdown = memo(function ConversationMarkdown({ text }: { text: string }) {
  const id = useId();
  const prefix = `message-${id.replace(/:/g, "")}-`;
  const components = useMemo(() => createComponents(prefix), [prefix]);
  return <div className={styles.prose}>
    <Markdown remarkPlugins={[remarkGfm]} skipHtml components={components}
      remarkRehypeOptions={{ clobberPrefix: prefix, footnoteLabel: "주석", footnoteBackLabel: "본문으로 돌아가기" }}>
      {text}
    </Markdown>
  </div>;
});
