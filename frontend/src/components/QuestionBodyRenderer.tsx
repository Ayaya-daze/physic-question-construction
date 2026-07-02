'use client';

import katex from 'katex';

type Format = 'markdown' | 'latex' | 'text';
type RenderBlock = { kind: 'line'; value: string } | { kind: 'math'; value: string };

function resolveAssetUrl(src: string, questionId: string): string {
  const trimmed = src.trim();
  if (/^(https?:|data:|blob:|\/)/i.test(trimmed)) {
    return trimmed;
  }
  const filename = trimmed.split('/').pop() || trimmed;
  return `/api/file-questions/${encodeURIComponent(questionId)}/assets/${encodeURIComponent(filename)}`;
}

function MathFragment({ value, displayMode = false }: { value: string; displayMode?: boolean }) {
  let html = value;
  try {
    html = katex.renderToString(value, {
      displayMode,
      throwOnError: false,
      strict: false,
      trust: false,
    });
  } catch {
    html = value;
  }
  return (
    <span
      className={displayMode ? 'my-3 block overflow-x-auto' : 'inline-block align-baseline'}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function _hasLatexCommands(text: string): boolean {
  // Detect bare LaTeX math that's not wrapped in delimiters:
  // - Commands: \frac, \mathrm, \vec, \sum ...
  // - Sub/superscript after variable/paren: v_0, x^2, E_{k}, (v_0) ...
  return /\\[a-zA-Z]/.test(text) || /[a-zA-Z)\]}][_^]\d/.test(text) || /[_^]\{/.test(text);
}

function InlineLatex({ text }: { text: string }) {
  const parts = text.split(/(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\\\[[\s\S]+?\\\]|\\\([^\n]+?\\\))/g);
  return (
    <>
      {parts.map((part, idx) => {
        if (!part) return null;
        if (part.startsWith('$$') && part.endsWith('$$')) {
          return <MathFragment key={idx} value={part.slice(2, -2)} displayMode />;
        }
        if (part.startsWith('\\[') && part.endsWith('\\]')) {
          return <MathFragment key={idx} value={part.slice(2, -2)} displayMode />;
        }
        if (part.startsWith('$') && part.endsWith('$')) {
          return <MathFragment key={idx} value={part.slice(1, -1)} />;
        }
        if (part.startsWith('\\(') && part.endsWith('\\)')) {
          return <MathFragment key={idx} value={part.slice(2, -2)} />;
        }
        // Auto-wrap bare LaTeX formulas that have no delimiters
        if (_hasLatexCommands(part)) {
          return <MathFragment key={idx} value={part} />;
        }
        return <span key={idx}>{part}</span>;
      })}
    </>
  );
}

function imageFromLine(line: string): { alt: string; src: string } | null {
  const markdown = line.match(/!\[([^\]]*)\]\(([^)]+)\)/);
  if (markdown) {
    return { alt: markdown[1] || '题图', src: markdown[2] };
  }
  const includeGraphics = line.match(/\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}/);
  if (includeGraphics) {
    return { alt: '题图', src: includeGraphics[1] };
  }
  return null;
}

function splitRenderBlocks(body: string): RenderBlock[] {
  const blocks: RenderBlock[] = [];
  const lines = body.replace(/\r\n/g, '\n').split('\n');
  let mathFence: '$$' | '\\[' | null = null;
  let mathLines: string[] = [];

  for (const line of lines) {
    const stripped = line.trim();
    if (!mathFence && (stripped === '$$' || stripped === '\\[')) {
      mathFence = stripped;
      mathLines = [];
      continue;
    }
    if (mathFence && ((mathFence === '$$' && stripped === '$$') || (mathFence === '\\[' && stripped === '\\]'))) {
      blocks.push({ kind: 'math', value: mathLines.join('\n') });
      mathFence = null;
      mathLines = [];
      continue;
    }
    if (mathFence) {
      mathLines.push(line);
      continue;
    }
    blocks.push({ kind: 'line', value: line });
  }

  if (mathFence) {
    blocks.push({ kind: 'line', value: mathFence });
    mathLines.forEach((line) => blocks.push({ kind: 'line', value: line }));
  }

  return blocks;
}

export default function QuestionBodyRenderer({
  body,
  format,
  questionId,
}: {
  body: string;
  format: Format;
  questionId: string;
}) {
  if (!body.trim()) {
    return <p className="text-sm text-gray-400">未提供内容</p>;
  }

  const blocks = splitRenderBlocks(body);

  return (
    <div className="space-y-2 text-[15px] leading-7 text-gray-900">
      {blocks.map((block, idx) => {
        if (block.kind === 'math') {
          return <MathFragment key={idx} value={block.value} displayMode />;
        }
        const line = block.value;
        const image = imageFromLine(line.trim());
        if (image) {
          return (
            <figure key={idx} className="my-4">
              <img
                src={resolveAssetUrl(image.src, questionId)}
                alt={image.alt}
                className="mx-auto max-h-[360px] max-w-full rounded border border-gray-200 bg-white object-contain sm:max-w-[76%]"
              />
              {image.alt && <figcaption className="mt-1 text-xs text-gray-500">{image.alt}</figcaption>}
            </figure>
          );
        }

        if (!line.trim()) {
          return <div key={idx} className="h-2" />;
        }

        if (format === 'markdown') {
          if (line.startsWith('### ')) {
            return <h4 key={idx} className="pt-2 text-base font-semibold"><InlineLatex text={line.slice(4)} /></h4>;
          }
          if (line.startsWith('## ')) {
            return <h3 key={idx} className="pt-3 text-lg font-semibold"><InlineLatex text={line.slice(3)} /></h3>;
          }
          if (line.startsWith('# ')) {
            return <h2 key={idx} className="pt-3 text-xl font-semibold"><InlineLatex text={line.slice(2)} /></h2>;
          }
          if (line.trimStart().startsWith('- ')) {
            return <p key={idx} className="pl-4"><span className="mr-2">•</span><InlineLatex text={line.trimStart().slice(2)} /></p>;
          }
        }

        return (
          <p key={idx} className="whitespace-pre-wrap">
            <InlineLatex text={line} />
          </p>
        );
      })}
    </div>
  );
}
