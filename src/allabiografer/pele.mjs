// Mermaid source on stdin, SVG on stdout, rendered by Pele from $PELE (its dist/pele.js).
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const { render } = await import(pathToFileURL(process.env.PELE).href);
process.stdout.write(render(readFileSync(0, "utf8"), { responsive: false, padding: 16 }).svg);
