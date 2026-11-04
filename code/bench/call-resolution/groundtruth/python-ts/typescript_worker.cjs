/* Emit call-site declarations with the TypeScript compiler checker. */
"use strict";

const fs = require("node:fs");
const crypto = require("node:crypto");
const path = require("node:path");
const MAX_PER_HINT = {
  constructor: 150,
  dynamic: 150,
  higher_order: 400,
  member: 400,
  named: 400,
};

function main() {
  const [rootArg, modulePath, rootsJson, suffixesJson] = process.argv.slice(2);
  const root = path.resolve(rootArg);
  const ts = require(modulePath);
  const roots = JSON.parse(rootsJson);
  const suffixes = new Set(JSON.parse(suffixesJson));
  const files = roots.flatMap((sourceRoot) =>
    listSources(path.join(root, sourceRoot), suffixes),
  );
  const config = readCompilerOptions(ts, root, roots);
  const options = {
    ...config,
    allowJs: true,
    checkJs: true,
    noEmit: true,
    skipLibCheck: true,
    target: config.target || ts.ScriptTarget.ES2022,
    moduleResolution: config.moduleResolution || ts.ModuleResolutionKind.Node10,
  };
  const program = ts.createProgram(files, options);
  const checker = program.getTypeChecker();
  const sourceSet = new Set(files.map((file) => path.resolve(file)));
  const candidates = [];
  for (const sourceFile of program.getSourceFiles()) {
    if (!sourceSet.has(path.resolve(sourceFile.fileName))) continue;
    collect(ts, sourceFile, candidates, []);
  }
  const selected = selectCandidates(ts, root, candidates);
  const sites = selected.map((candidate) =>
    callSite(ts, checker, root, candidate.call, candidate.parents),
  );
  process.stdout.write(JSON.stringify(sites));
}

function listSources(directory, suffixes) {
  if (!fs.existsSync(directory)) return [];
  const output = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (excludedDirectory(entry.name)) continue;
      output.push(...listSources(path.join(directory, entry.name), suffixes));
      continue;
    }
    if (suffixes.has(path.extname(entry.name))) {
      output.push(path.join(directory, entry.name));
    }
  }
  return output.sort();
}

function excludedDirectory(name) {
  return new Set([
    ".git",
    "__tests__",
    "coverage",
    "dist",
    "generated",
    "node_modules",
    "test",
    "tests",
    "vendor",
  ]).has(name.toLowerCase());
}

function readCompilerOptions(ts, root, sourceRoots) {
  for (const sourceRoot of sourceRoots) {
    let directory = path.join(root, sourceRoot);
    while (directory.startsWith(root)) {
      const configPath = path.join(directory, "tsconfig.json");
      if (fs.existsSync(configPath)) {
        const config = ts.readConfigFile(configPath, ts.sys.readFile);
        if (config.error) break;
        const parsed = ts.parseJsonConfigFileContent(
          config.config,
          ts.sys,
          directory,
          undefined,
          configPath,
        );
        return parsed.options;
      }
      if (directory === root) break;
      directory = path.dirname(directory);
    }
  }
  return {};
}

function collect(ts, sourceFile, candidates, parents) {
  function visit(node, activeParents) {
    let active = activeParents;
    if (ts.isFunctionLike(node)) {
      const name = functionName(ts, node);
      const line = node.getSourceFile().getLineAndCharacterOfPosition(node.getStart()).line + 1;
      active = [...activeParents, { name, line }];
    }
    if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
      candidates.push({ call: node, parents: active, hint: syntaxHint(ts, node) });
    }
    ts.forEachChild(node, (child) => visit(child, active));
  }
  visit(sourceFile, parents);
}

function syntaxHint(ts, call) {
  if (ts.isNewExpression(call)) return "constructor";
  if (ts.isPropertyAccessExpression(call.expression)) return "member";
  if (ts.isCallExpression(call.expression)) return "higher_order";
  if (ts.isIdentifier(call.expression)) return "named";
  return "dynamic";
}

function selectCandidates(ts, root, candidates) {
  const groups = new Map();
  for (const candidate of candidates) {
    const group = groups.get(candidate.hint) || [];
    group.push(candidate);
    groups.set(candidate.hint, group);
  }
  const selected = [];
  for (const [hint, group] of groups) {
    group.sort((left, right) => compareText(candidateKey(left, root, hint), candidateKey(right, root, hint)));
    selected.push(...group.slice(0, MAX_PER_HINT[hint] || 150));
  }
  return selected.sort((left, right) => {
    const a = left.call.getSourceFile().fileName;
    const b = right.call.getSourceFile().fileName;
    return compareText(path.relative(root, a), path.relative(root, b)) || left.call.getStart() - right.call.getStart();
  });
}

function candidateKey(candidate, root, hint) {
  const call = candidate.call;
  const source = call.getSourceFile();
  const position = source.getLineAndCharacterOfPosition(call.getStart());
  const relative = path.relative(root, source.fileName).split(path.sep).join("/");
  const identity = `${relative}:${position.line + 1}:${call.getStart()}:${hint}`;
  return crypto.createHash("sha256").update(identity).digest("hex");
}

function compareText(left, right) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function callSite(ts, checker, root, call, parents) {
  const source = call.getSourceFile();
  const file = path.relative(root, source.fileName).split(path.sep).join("/");
  const line = source.getLineAndCharacterOfPosition(call.getStart()).line + 1;
  let signature;
  try {
    signature = checker.getResolvedSignature(call);
  } catch {
    signature = undefined;
  }
  const declaration = concreteDeclaration(ts, checker, call, signature);
  const dynamic = isDynamic(ts, checker, call, declaration);
  const target = declaration && !dynamic ? targetInfo(ts, root, declaration) : undefined;
  const targetExternal = Boolean(declaration && !dynamic && !target);
  const callClass = classify(ts, checker, call, file, target, declaration, dynamic);
  return {
    file,
    line,
    call_name: callName(ts, call.expression),
    call_class: callClass,
    target_id: target ? target.id : null,
    target_module: target ? target.module : null,
    external: targetExternal,
    truth_source: "typescript-compiler-api-" + ts.version,
    function_id: parents.length ? functionId(file, parents) : null,
    module: moduleName(file),
  };
}

function callName(ts, expression) {
  if (ts.isIdentifier(expression)) return expression.text;
  if (ts.isPropertyAccessExpression(expression)) return expression.name.text;
  if (ts.isElementAccessExpression(expression)) {
    const argument = expression.argumentExpression;
    if (argument && (ts.isStringLiteral(argument) || ts.isNumericLiteral(argument))) {
      return argument.text;
    }
  }
  if (ts.isCallExpression(expression)) return callName(ts, expression.expression);
  return expression.getText();
}

function concreteDeclaration(ts, checker, call, signature) {
  if (!signature) return undefined;
  const selected = signature.getDeclaration();
  if (selected && hasBody(ts, selected)) return selected;
  let symbol;
  try {
    symbol = checker.getSymbolAtLocation(call.expression);
    if (symbol && symbol.flags & ts.SymbolFlags.Alias) {
      symbol = checker.getAliasedSymbol(symbol);
    }
  } catch {
    return selected;
  }
  const implementations = (symbol && symbol.getDeclarations() || []).filter(
    (declaration) => hasBody(ts, declaration),
  );
  if (implementations.length === 1) return implementations[0];
  return selected;
}

function hasBody(ts, declaration) {
  return Boolean(
    declaration.body ||
      (ts.isConstructorDeclaration(declaration) && declaration.body),
  );
}

function isDynamic(ts, checker, call, declaration) {
  if (declaration && hasBody(ts, declaration)) return false;
  if (declaration && ts.isMethodSignature(declaration)) return true;
  if (declaration && ts.isCallSignatureDeclaration(declaration)) return true;
  const type = checker.getTypeAtLocation(call.expression);
  if (type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) return true;
  if (!declaration) return true;
  return Boolean(ts.getCombinedModifierFlags(declaration) & ts.ModifierFlags.Abstract);
}

function classify(ts, checker, call, callerFile, target, declaration, dynamic) {
  if (ts.isNewExpression(call)) return "constructor";
  if (ts.isCallExpression(call.expression)) return "higher_order";
  if (dynamic && !target) {
    if (isCallableValue(ts, checker, call.expression, declaration)) return "higher_order";
    return "dynamic";
  }
  if (declaration && ts.isConstructorDeclaration(declaration)) return "constructor";
  if (ts.isNewExpression(call)) return "constructor";
  if (ts.isPropertyAccessExpression(call.expression)) return "member";
  if (!target) return "dynamic";
  return target.file === callerFile ? "same_file" : "imported";
}

function isCallableValue(ts, checker, expression, declaration) {
  if (
    ts.isIdentifier(expression) &&
    new Set(["eval", "Function", "require"]).has(expression.text)
  ) {
    return false;
  }
  if (ts.isCallExpression(expression)) return true;
  let symbol;
  try {
    symbol = checker.getSymbolAtLocation(expression);
    if (symbol && symbol.flags & ts.SymbolFlags.Alias) {
      symbol = checker.getAliasedSymbol(symbol);
    }
  } catch {
    symbol = undefined;
  }
  const declarations = symbol && symbol.getDeclarations() || [];
  if (
    declarations.some(
      (item) => ts.isParameter(item) || ts.isVariableDeclaration(item),
    )
  ) {
    return true;
  }
  const name = declaration && declaration.name;
  return Boolean(
    ts.isIdentifier(expression) &&
      name &&
      (ts.isParameter(name.parent) || ts.isVariableDeclaration(name.parent)),
  );
}

function targetInfo(ts, root, declaration) {
  const source = declaration.getSourceFile();
  const absolute = path.resolve(source.fileName);
  if (!absolute.startsWith(root + path.sep)) return undefined;
  const file = path.relative(root, absolute).split(path.sep).join("/");
  const line = source.getLineAndCharacterOfPosition(declaration.getStart()).line + 1;
  const name = functionNameFromDeclaration(ts, declaration);
  return { id: `${file}::${name}@${line}`, file, module: moduleName(file) };
}

function functionNameFromDeclaration(ts, declaration) {
  if (
    declaration.kind === ts.SyntaxKind.Constructor &&
    declaration.parent &&
    declaration.parent.name
  ) {
    return `${declaration.parent.name.getText()}.constructor`;
  }
  if (declaration.name && declaration.name.getText) return declaration.name.getText();
  return "<anonymous>";
}

function functionName(ts, node) {
  if (node.name && node.name.getText) return node.name.getText();
  if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) return "<anonymous>";
  return "<callable>";
}

function functionId(file, parents) {
  const last = parents[parents.length - 1];
  const name = parents.map((parent) => parent.name).join(".");
  return `${file}::${name}@${last.line}`;
}

function moduleName(file) {
  return file.replace(/\.[^.]+$/, "").replaceAll("/", ".");
}

main();
