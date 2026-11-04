using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

// Match rule: SymbolInfo supplies the declaration, even for virtual/interface
// calls; runtime overrides are not guessed. dynamic/unknown covers the C#
// dynamic keyword, a dynamic receiver and the reflection surface (Invoke,
// InvokeMember, GetValue, SetValue, CreateDelegate, Activator.CreateInstance);
// invoking a delegate variable is higher-order/unknown. nameof, typeof, sizeof,
// default and a target-typed new without a constructor are not call sites, and
// generated files (checked-in generator output) are not sampled. References are
// the runtime assemblies first, then project, package and framework-reference
// assemblies, one per assembly name.
internal static class RoslynTargets
{
    // Symbols the .NET SDK defines for a net10.0 Debug build; without them, code
    // behind #if directives is not parsed and its types stay unbound.
    private static readonly string[] Net10Symbols =
    {
        "NET", "NET10_0", "NETCOREAPP",
        "NET5_0_OR_GREATER", "NET6_0_OR_GREATER", "NET7_0_OR_GREATER",
        "NET8_0_OR_GREATER", "NET9_0_OR_GREATER", "NET10_0_OR_GREATER",
        "DEBUG", "TRACE",
    };

    private static string repo = "";
    private static string repoRoot = "";
    private static string sourceRoot = "";
    private static string source = "";
    private static string? caller;
    private static SemanticModel? model;
    private static bool isGenerated;

    private static int Main(string[] args)
    {
        if (args.Length is not (4 or 5))
        {
            Console.Error.WriteLine("usage: RoslynTargets <repo> <repo-root> <source-root> <reference-list> [<extra-source-list>]");
            return 2;
        }
        repo = args[0];
        repoRoot = Path.GetFullPath(args[1]);
        sourceRoot = Path.GetFullPath(args[2]);
        var extraReferences = File.Exists(args[3])
            ? File.ReadAllLines(args[3]).Where(File.Exists)
            : Enumerable.Empty<string>();
        var references = ((string?)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") ?? "")
            .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries)
            .Concat(extraReferences)
            .Distinct(StringComparer.Ordinal)
            .GroupBy(Path.GetFileNameWithoutExtension, StringComparer.OrdinalIgnoreCase)
            .Select(group => MetadataReference.CreateFromFile(group.First()));
        var extraSources = args.Length == 5 && File.Exists(args[4])
            ? File.ReadAllLines(args[4]).Where(File.Exists)
            : Enumerable.Empty<string>();
        var files = Directory.EnumerateFiles(sourceRoot, "*.cs", SearchOption.AllDirectories)
            .Where(path => !path.Contains("/obj/", StringComparison.Ordinal)
                && !path.Contains("/bin/", StringComparison.Ordinal))
            .Concat(extraSources)
            .Distinct(StringComparer.Ordinal)
            .Order(StringComparer.Ordinal)
            .ToArray();
        if (files.Length == 0)
        {
            Console.Error.WriteLine($"no C# source files under {sourceRoot}");
            return 2;
        }
        var parseOptions = new CSharpParseOptions(preprocessorSymbols: Net10Symbols);
        var trees = new List<SyntaxTree>();
        var generated = new List<bool>();
        foreach (var path in files)
        {
            var text = File.ReadAllText(path);
            trees.Add(CSharpSyntaxTree.ParseText(text, parseOptions, path: Path.GetFullPath(path)));
            generated.Add(IsGenerated(path, text));
        }
        var compilation = CSharpCompilation.Create(
            "CallAudit", trees, references,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
        for (var index = 0; index < trees.Count; index++)
        {
            var tree = trees[index];
            source = Path.GetFullPath(tree.FilePath);
            isGenerated = generated[index];
            model = compilation.GetSemanticModel(tree, ignoreAccessibility: true);
            new Calls().Visit(tree.GetRoot());
        }
        return 0;
    }

    /// <summary>Generated sources are excluded from the audit sample (D6).</summary>
    private static bool IsGenerated(string path, string text)
    {
        var normalized = path.Replace('\\', '/');
        if (normalized.EndsWith(".Generated.cs", StringComparison.OrdinalIgnoreCase)
            || normalized.EndsWith(".g.cs", StringComparison.OrdinalIgnoreCase)
            || normalized.Contains("Internal.Generated", StringComparison.Ordinal)
            || normalized.Contains("/gen/", StringComparison.Ordinal)
            || normalized.Contains("/generated/", StringComparison.OrdinalIgnoreCase)
            || normalized.Contains("/obj/", StringComparison.Ordinal)
            || normalized.Contains("/bin/", StringComparison.Ordinal))
        {
            return true;
        }
        return text.Split('\n').Take(8)
            .Any(line => line.Contains("<auto-generated", StringComparison.OrdinalIgnoreCase));
    }

    private sealed class Calls : CSharpSyntaxWalker
    {
        public override void VisitMethodDeclaration(MethodDeclarationSyntax node)
        {
            WithCaller(node, () => base.VisitMethodDeclaration(node));
        }

        public override void VisitConstructorDeclaration(ConstructorDeclarationSyntax node)
        {
            WithCaller(node, () => base.VisitConstructorDeclaration(node));
        }

        public override void VisitLocalFunctionStatement(LocalFunctionStatementSyntax node)
        {
            WithCaller(node, () => base.VisitLocalFunctionStatement(node));
        }

        public override void VisitInvocationExpression(InvocationExpressionSyntax node)
        {
            var symbol = model!.GetSymbolInfo(node).Symbol as IMethodSymbol;
            if (!IsNameOf(node))
            {
                Emit(node, symbol, "method");
            }
            base.VisitInvocationExpression(node);
        }

        public override void VisitObjectCreationExpression(ObjectCreationExpressionSyntax node)
        {
            Emit(node, model!.GetSymbolInfo(node).Symbol as IMethodSymbol, "constructor");
            base.VisitObjectCreationExpression(node);
        }

        public override void VisitImplicitObjectCreationExpression(
            ImplicitObjectCreationExpressionSyntax node)
        {
            var symbol = model!.GetSymbolInfo(node).Symbol as IMethodSymbol;
            if (symbol is not null)
            {
                Emit(node, symbol, "constructor");
            }
            base.VisitImplicitObjectCreationExpression(node);
        }

        private static bool IsNameOf(InvocationExpressionSyntax node) =>
            node.Expression is IdentifierNameSyntax identifier
            && identifier.Identifier.ValueText == "nameof"
            && model!.GetSymbolInfo(node).Symbol is null;

        private void WithCaller(SyntaxNode node, Action visit)
        {
            var previous = caller;
            var method = model!.GetDeclaredSymbol(node) as IMethodSymbol;
            caller = method is null ? null : MethodId(source, method);
            visit();
            caller = previous;
        }

        private static void Emit(SyntaxNode node, IMethodSymbol? symbol, string kind)
        {
            if (isGenerated) return;
            var declaration = symbol?.DeclaringSyntaxReferences.FirstOrDefault();
            var targetFile = declaration is null ? null : Path.GetFullPath(declaration.SyntaxTree.FilePath);
            var projectTarget = targetFile is not null
                && targetFile.StartsWith(sourceRoot + Path.DirectorySeparatorChar, StringComparison.Ordinal);
            var target = symbol is null ? null : MethodId(targetFile ?? source, symbol);
            var higherOrder = symbol?.MethodKind == MethodKind.DelegateInvoke
                || node is InvocationExpressionSyntax delegateInvocation
                    && model!.GetTypeInfo(delegateInvocation.Expression).Type?.TypeKind == TypeKind.Delegate;
            var isDynamicKeyword = node is InvocationExpressionSyntax dynamicInvocation
                && model!.GetTypeInfo(dynamicInvocation.Expression).Type?.TypeKind == TypeKind.Dynamic;
            var dynamicCall = isDynamicKeyword || IsReflection(symbol);
            var callClass = kind == "constructor" ? "constructor"
                : higherOrder ? "higher_order"
                : dynamicCall ? "dynamic"
                : projectTarget && targetFile != source ? "imported"
                : node is InvocationExpressionSyntax invocation
                    && invocation.Expression is MemberAccessExpressionSyntax ? "member"
                : "same_file";
            var targetKind = higherOrder || dynamicCall ? "dynamic"
                : symbol is null ? null : projectTarget ? "project" : "external";
            var relative = Path.GetRelativePath(repoRoot, source).Replace(Path.DirectorySeparatorChar, '/');
            var module = Path.GetDirectoryName(relative)?.Replace(Path.DirectorySeparatorChar, '/') ?? "";
            var targetModule = projectTarget
                ? Path.GetDirectoryName(Path.GetRelativePath(repoRoot, targetFile!))?
                    .Replace(Path.DirectorySeparatorChar, '/')
                : null;
            var data = new
            {
                repo,
                file = relative,
                line = node.GetLocation().GetLineSpan().StartLinePosition.Line + 1,
                call_class = callClass,
                call_name = CallName(node, symbol),
                target = projectTarget ? target : null,
                target_kind = targetKind,
                caller,
                module,
                target_module = targetModule,
                truth_source = "roslyn:5.9.0-1.26423.113",
            };
            Console.WriteLine(JsonSerializer.Serialize(data));
        }

        /// <summary>The reflection surface: the real target is a member reached
        /// through reflection metadata rather than named at the call site.</summary>
        private static bool IsReflection(IMethodSymbol? symbol)
        {
            if (symbol is null) return false;
            var type = symbol.ContainingType.ToDisplayString();
            if (type == "System.Activator") return symbol.Name == "CreateInstance";
            return type.StartsWith("System.Reflection.", StringComparison.Ordinal)
                && symbol.Name is "Invoke" or "InvokeMember" or "GetValue" or "SetValue"
                    or "CreateDelegate";
        }

        private static string MethodId(string file, IMethodSymbol method)
        {
            var relative = Path.GetRelativePath(repoRoot, file).Replace(Path.DirectorySeparatorChar, '/');
            return $"{relative}::{method.ToDisplayString(SymbolDisplayFormat.CSharpErrorMessageFormat)}";
        }

        private static string CallName(SyntaxNode node, IMethodSymbol? symbol)
        {
            if (node is ObjectCreationExpressionSyntax creation)
                return creation.Type is SimpleNameSyntax simple ? simple.Identifier.ValueText : creation.Type.ToString();
            if (node is ImplicitObjectCreationExpressionSyntax)
                return symbol?.ContainingType.Name ?? "unknown";
            if (node is not InvocationExpressionSyntax invocation) return symbol?.Name ?? "unknown";
            return invocation.Expression switch
            {
                SimpleNameSyntax simple => simple.Identifier.ValueText,
                MemberAccessExpressionSyntax member => member.Name.Identifier.ValueText,
                MemberBindingExpressionSyntax binding => binding.Name.Identifier.ValueText,
                _ => symbol?.Name ?? invocation.Expression.ToString(),
            };
        }
    }
}
