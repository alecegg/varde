package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/token"
	"go/types"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/tools/go/packages"
)

type record struct {
	Repo              string  `json:"repo"`
	Language          string  `json:"language"`
	File              string  `json:"file"`
	Line              int     `json:"line"`
	CallName          string  `json:"call_name"`
	CallClass         string  `json:"call_class"`
	GroundTruth       string  `json:"ground_truth"`
	MeasuredEdge      *string `json:"measured_edge"`
	MeasuredStatus    string  `json:"measured_status"`
	TruthSource       string  `json:"truth_source"`
	FunctionID        *string `json:"function_id"`
	Module            *string `json:"module"`
	GroundTruthModule *string `json:"ground_truth_module"`
	MeasuredModule    *string `json:"measured_module"`
	CalleeKind        string  `json:"_callee_kind"`
}

func main() {
	if len(os.Args) != 3 {
		panic("usage: go-types <repo-path> <repo-name>")
	}
	root, err := filepath.Abs(os.Args[1])
	must(err)
	fset := token.NewFileSet()
	cfg := &packages.Config{
		Mode: packages.NeedName | packages.NeedFiles | packages.NeedSyntax | packages.NeedTypes | packages.NeedTypesInfo | packages.NeedDeps,
		Dir:  root,
		Fset: fset,
	}
	pkgs, err := packages.Load(cfg, "./...")
	must(err)
	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()
	enc := json.NewEncoder(w)
	for _, pkg := range pkgs {
		for _, file := range pkg.Syntax {
			ast.Inspect(file, func(node ast.Node) bool {
				switch fn := node.(type) {
				case *ast.FuncDecl:
					writeFunctionCalls(root, os.Args[2], pkg, file, fn, fset, enc)
				case *ast.FuncLit:
					caller := &ast.FuncDecl{Name: ast.NewIdent("literal"), Type: fn.Type, Body: fn.Body}
					writeFunctionCalls(root, os.Args[2], pkg, file, caller, fset, enc)
				}
				return true
			})
		}
	}

}

func writeFunctionCalls(root, repo string, pkg *packages.Package, file *ast.File, caller *ast.FuncDecl, fset *token.FileSet, enc *json.Encoder) {
	if caller.Body == nil {
		return
	}
	ast.Inspect(caller.Body, func(node ast.Node) bool {
		if node == nil {
			return true
		}
		if node != caller.Body {
			switch node.(type) {
			case *ast.FuncDecl, *ast.FuncLit:
				return false
			}
		}
		call, ok := node.(*ast.CallExpr)
		if !ok {
			return true
		}
		record, ok := callRecord(root, repo, pkg, file, call, caller, fset)
		if ok {
			must(enc.Encode(record))
		}
		return true
	})
}

func callRecord(root, repo string, pkg *packages.Package, file *ast.File, call *ast.CallExpr, caller *ast.FuncDecl, fset *token.FileSet) (record, bool) {
	callPos := fset.Position(call.Pos())
	callerID := ""
	if caller != nil {
		pos := fset.Position(caller.Pos())
		callerID = fmt.Sprintf("%s:%d:%s", repoPath(root, pos.Filename), pos.Line, caller.Name.Name)
	}
	callerModule := pkg.PkgPath
	callee := call.Fun
	var obj types.Object
	if pkg.TypesInfo != nil {
		switch fun := callee.(type) {
		case *ast.Ident:
			obj = pkg.TypesInfo.Uses[fun]
		case *ast.SelectorExpr:
			obj = pkg.TypesInfo.Uses[fun.Sel]
		}
	}
	calleeKind := calleeKindOf(pkg, callee, obj)
	if calleeKind == "builtin" || calleeKind == "conversion" {
		// len/make/append/... and T(x) are not calls to a project function.
		return record{}, false
	}
	callClass := "same_file"
	if _, ok := callee.(*ast.SelectorExpr); ok {
		callClass = "member"
	}
	truth, truthModule := "unknown", ""
	status := "opaque"
	if fn, ok := obj.(*types.Func); ok {
		pos := fset.Position(fn.Pos())
		if pos.IsValid() && within(root, pos.Filename) {
			truth = fmt.Sprintf("%s:%d:%s", repoPath(root, pos.Filename), pos.Line, fn.Name())
			truthModule = fn.Pkg().Path()
			status = "unresolved"
			if filepath.Dir(pos.Filename) != filepath.Dir(callPos.Filename) {
				callClass = "imported"
			}
			if strings.HasPrefix(fn.Name(), "New") {
				callClass = "constructor"
			}
		} else {
			truth = "external"
			status = "external"
		}
	} else if calleeKind == "value" {
		// Call through a function value (local, parameter, field): higher order.
		callClass = "higher_order"
	} else if obj != nil && obj.Pkg() != nil && obj.Pkg().Path() != pkg.PkgPath {
		truth = "external"
		status = "external"
	} else {
		callClass = "dynamic"
	}
	if callClass == "member" && truth == "unknown" {
		callClass = "dynamic"
	}
	return record{
		Repo: repo, Language: "go", File: repoPath(root, callPos.Filename), Line: callPos.Line,
		CallName: calledName(callee), CallClass: callClass, GroundTruth: truth, MeasuredEdge: nil, MeasuredStatus: status,
		TruthSource: "go/types", FunctionID: stringPtr(callerID), Module: stringPtr(callerModule),
		GroundTruthModule: stringPtr(truthModule), MeasuredModule: nil, CalleeKind: calleeKind,
	}, caller != nil
}

// calleeKindOf separates real calls from Go builtins and type conversions, and
// marks calls through a function-typed value as higher order.
func calleeKindOf(pkg *packages.Package, callee ast.Expr, obj types.Object) string {
	if _, ok := obj.(*types.Builtin); ok {
		return "builtin"
	}
	if pkg.TypesInfo == nil {
		return "unknown"
	}
	tv, ok := pkg.TypesInfo.Types[callee]
	if !ok || tv.Type == nil {
		return "unknown"
	}
	if tv.IsType() {
		return "conversion"
	}
	if _, ok := obj.(*types.Func); ok {
		return "function"
	}
	if _, ok := tv.Type.Underlying().(*types.Signature); ok {
		return "value"
	}
	return "unknown"
}

func calledName(expr ast.Expr) string {
	switch fun := expr.(type) {
	case *ast.Ident:
		return fun.Name
	case *ast.SelectorExpr:
		return fun.Sel.Name
	case *ast.IndexExpr:
		return calledName(fun.X)
	case *ast.IndexListExpr:
		return calledName(fun.X)
	case *ast.ParenExpr:
		return calledName(fun.X)
	default:
		return "unknown"
	}
}

func within(root, path string) bool {
	rel, err := filepath.Rel(root, path)
	return err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

func repoPath(root, path string) string {
	rel, err := filepath.Rel(root, path)
	if err != nil {
		return filepath.ToSlash(path)
	}
	return filepath.ToSlash(rel)
}

func stringPtr(value string) *string {
	if value == "" {
		return nil
	}
	return &value
}

func must(err error) {
	if err != nil {
		panic(err)
	}
}
