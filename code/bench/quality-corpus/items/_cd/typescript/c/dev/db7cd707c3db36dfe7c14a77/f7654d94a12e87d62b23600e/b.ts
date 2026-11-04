// SPDX-License-Identifier: Apache-2.0

function getTypeOfInitializer(node: Expression) {
            // Return the cached type if one is available. If the type of the variable was inferred
            // from its initializer, we'll already have cached the type. Otherwise we compute it now
            // without caching such that transient types are reflected.
            const links = getNodeLinks(node);
            return links.resolvedType || getTypeOfExpression(node);
        }

function getFlowTypeOfReference(reference: Node, declaredType: Type, initialType = declaredType, flowContainer?: Node, couldBeUninitialized?: boolean) {
            let key: string | undefined;
            let keySet = false;
            let flowDepth = 0;
            if (flowAnalysisDisabled) {
                return errorType;
            }
            if (!reference.flowNode || !couldBeUninitialized && !(declaredType.flags & TypeFlags.Narrowable)) {
                return declaredType;
            }
            flowInvocationCount++;
            const sharedFlowStart = sharedFlowCount;
            const evolvedType = getTypeFromFlowType(getTypeAtFlowNode(reference.flowNode));
            sharedFlowCount = sharedFlowStart;
            // When the reference is 'x' in an 'x.length', 'x.push(value)', 'x.unshift(value)' or x[n] = value' operation,
            // we give type 'any[]' to 'x' instead of using the type determined by control flow analysis such that operations
            // on empty arrays are possible without implicit any errors and new element types can be inferred without
            // type mismatch errors.
            const resultType = getObjectFlags(evolvedType) & ObjectFlags.EvolvingArray && isEvolvingArrayOperationTarget(reference) ? autoArrayType : finalizeEvolvingArrayType(evolvedType);
            if (reference.parent && reference.parent.kind === SyntaxKind.NonNullExpression && getTypeWithFacts(resultType, TypeFacts.NEUndefinedOrNull).flags & TypeFlags.Never) {
                return declaredType;
            }
            return resultType;

            function getOrSetCacheKey() {
                if (keySet) {
                    return key;
                }
                keySet = true;
                return key = getFlowCacheKey(reference, declaredType, initialType, flowContainer);
            }

            function getTypeAtFlowNode(flow: FlowNode): FlowType {
                if (flowDepth === 2000) {
                    // We have made 2000 recursive invocations. To avoid overflowing the call stack we report an error
                    // and disable further control flow analysis in the containing function or module body.
                    flowAnalysisDisabled = true;
                    reportFlowControlError(reference);
                    return errorType;
                }
                flowDepth++;
                while (true) {
                    const flags = flow.flags;
                    if (flags & FlowFlags.Shared) {
                        // We cache results of flow type resolution for shared nodes that were previously visited in
                        // the same getFlowTypeOfReference invocation. A node is considered shared when it is the
                        // antecedent of more than one node.
                        for (let i = sharedFlowStart; i < sharedFlowCount; i++) {
                            if (sharedFlowNodes[i] === flow) {
                                flowDepth--;
                                return sharedFlowTypes[i];
                            }
                        }
                    }
                    let type: FlowType | undefined;
                    if (flags & FlowFlags.AfterFinally) {
                        // block flow edge: finally -> pre-try (for larger explanation check comment in binder.ts - bindTryStatement
                        (<AfterFinallyFlow>flow).locked = true;
                        type = getTypeAtFlowNode((<AfterFinallyFlow>flow).antecedent);
                        (<AfterFinallyFlow>flow).locked = false;
                    }
                    else if (flags & FlowFlags.PreFinally) {
                        // locked pre-finally flows are filtered out in getTypeAtFlowBranchLabel
                        // so here just redirect to antecedent
                        flow = (<PreFinallyFlow>flow).antecedent;
                        continue;
                    }
                    else if (flags & FlowFlags.Assignment) {
                        type = getTypeAtFlowAssignment(<FlowAssignment>flow);
                        if (!type) {
                            flow = (<FlowAssignment>flow).antecedent;
                            continue;
                        }
                    }
                    else if (flags & FlowFlags.Condition) {
                        type = getTypeAtFlowCondition(<FlowCondition>flow);
                    }
                    else if (flags & FlowFlags.SwitchClause) {
                        type = getTypeAtSwitchClause(<FlowSwitchClause>flow);
                    }
                    else if (flags & FlowFlags.Label) {
                        if ((<FlowLabel>flow).antecedents!.length === 1) {
                            flow = (<FlowLabel>flow).antecedents![0];
                            continue;
                        }
                        type = flags & FlowFlags.BranchLabel ?
                            getTypeAtFlowBranchLabel(<FlowLabel>flow) :
                            getTypeAtFlowLoopLabel(<FlowLabel>flow);
                    }
                    else if (flags & FlowFlags.ArrayMutation) {
                        type = getTypeAtFlowArrayMutation(<FlowArrayMutation>flow);
                        if (!type) {
                            flow = (<FlowArrayMutation>flow).antecedent;
                            continue;
                        }
                    }
                    else if (flags & FlowFlags.Start) {
                        // Check if we should continue with the control flow of the containing function.
                        const container = (<FlowStart>flow).container;
                        if (container && container !== flowContainer &&
                            reference.kind !== SyntaxKind.PropertyAccessExpression &&
                            reference.kind !== SyntaxKind.ElementAccessExpression &&
                            reference.kind !== SyntaxKind.ThisKeyword) {
                            flow = container.flowNode!;
                            continue;
                        }
                        // At the top of the flow we have the initial type.
                        type = initialType;
                    }
                    else {
                        // Unreachable code errors are reported in the binding phase. Here we
                        // simply return the non-auto declared type to reduce follow-on errors.
                        type = convertAutoToAny(declaredType);
                    }
                    if (flags & FlowFlags.Shared) {
                        // Record visited node and the associated type in the cache.
                        sharedFlowNodes[sharedFlowCount] = flow;
                        sharedFlowTypes[sharedFlowCount] = type;
                        sharedFlowCount++;
                    }
                    flowDepth--;
                    return type;
                }
            }

            function getInitialOrAssignedType(flow: FlowAssignment) {
                const node = flow.node;
                if (flow.flags & FlowFlags.Cached) {
                    const cached = flowAssignmentTypes[getNodeId(node)];
                    if (cached) {
                        return cached;
                    }
                }
                const startInvocationCount = flowInvocationCount;
                const type = getConstraintForLocation(node.kind === SyntaxKind.VariableDeclaration || node.kind === SyntaxKind.BindingElement ?
                    getInitialType(<VariableDeclaration | BindingElement>node) :
                    getAssignedType(node), reference);
                // We cache the assigned type when getFlowTypeOfReference was recursively invoked in the
                // resolution of the assigned type and we're not within loop analysis.
                if (flowInvocationCount !== startInvocationCount && flowLoopCount === flowLoopStart) {
                    flow.flags |= FlowFlags.Cached;
                    flowAssignmentTypes[getNodeId(node)] = type;
                }
                return type;
            }

            function getTypeAtFlowAssignment(flow: FlowAssignment) {
                const node = flow.node;
                // Assignments only narrow the computed type if the declared type is a union type. Thus, we
                // only need to evaluate the assigned type if the declared type is a union type.
                if (isMatchingReference(reference, node)) {
                    if (getAssignmentTargetKind(node) === AssignmentKind.Compound) {
                        const flowType = getTypeAtFlowNode(flow.antecedent);
                        return createFlowType(getBaseTypeOfLiteralType(getTypeFromFlowType(flowType)), isIncomplete(flowType));
                    }
                    if (declaredType === autoType || declaredType === autoArrayType) {
                        if (isEmptyArrayAssignment(node)) {
                            return getEvolvingArrayType(neverType);
                        }
                        const assignedType = getBaseTypeOfLiteralType(getInitialOrAssignedType(flow));
                        return isTypeAssignableTo(assignedType, declaredType) ? assignedType : anyArrayType;
                    }
                    if (declaredType.flags & TypeFlags.Union) {
                        return getAssignmentReducedType(<UnionType>declaredType, getInitialOrAssignedType(flow));
                    }
                    return declaredType;
                }
                // We didn't have a direct match. However, if the reference is a dotted name, this
                // may be an assignment to a left hand part of the reference. For example, for a
                // reference 'x.y.z', we may be at an assignment to 'x.y' or 'x'. In that case,
                // return the declared type.
                if (containsMatchingReference(reference, node)) {
                    // A matching dotted name might also be an expando property on a function *expression*,
                    // in which case we continue control flow analysis back to the function's declaration
                    if (isVariableDeclaration(node) && (isInJSFile(node) || isVarConst(node))) {
                        const init = getDeclaredExpandoInitializer(node);
                        if (init && (init.kind === SyntaxKind.FunctionExpression || init.kind === SyntaxKind.ArrowFunction)) {
                            return getTypeAtFlowNode(flow.antecedent);
                        }
                    }
                    return declaredType;
                }
                // for (const _ in ref) acts as a nonnull on ref
                if (isVariableDeclaration(node) && node.parent.parent.kind === SyntaxKind.ForInStatement && isMatchingReference(reference, node.parent.parent.expression)) {
                    return getNonNullableTypeIfNeeded(getTypeFromFlowType(getTypeAtFlowNode(flow.antecedent)));
                }
                // Assignment doesn't affect reference
                return undefined;
            }

            function getTypeAtFlowArrayMutation(flow: FlowArrayMutation): FlowType | undefined {
                if (declaredType === autoType || declaredType === autoArrayType) {
                    const node = flow.node;
                    const expr = node.kind === SyntaxKind.CallExpression ?
                        (<PropertyAccessExpression>node.expression).expression :
                        (<ElementAccessExpression>node.left).expression;
                    if (isMatchingReference(reference, getReferenceCandidate(expr))) {
                        const flowType = getTypeAtFlowNode(flow.antecedent);
                        const type = getTypeFromFlowType(flowType);
                        if (getObjectFlags(type) & ObjectFlags.EvolvingArray) {
                            let evolvedType = <EvolvingArrayType>type;
                            if (node.kind === SyntaxKind.CallExpression) {
                                for (const arg of node.arguments) {
                                    evolvedType = addEvolvingArrayElementType(evolvedType, arg);
                                }
                            }
                            else {
                                // We must get the context free expression type so as to not recur in an uncached fashion on the LHS (which causes exponential blowup in compile time)
                                const indexType = getContextFreeTypeOfExpression((<ElementAccessExpression>node.left).argumentExpression);
                                if (isTypeAssignableToKind(indexType, TypeFlags.NumberLike)) {
                                    evolvedType = addEvolvingArrayElementType(evolvedType, node.right);
                                }
                            }
                            return evolvedType === type ? flowType : createFlowType(evolvedType, isIncomplete(flowType));
                        }
                        return flowType;
                    }
                }
                return undefined;
            }

            function getTypeAtFlowCondition(flow: FlowCondition): FlowType {
                const flowType = getTypeAtFlowNode(flow.antecedent);
                const type = getTypeFromFlowType(flowType);
                if (type.flags & TypeFlags.Never) {
                    return flowType;
                }
                // If we have an antecedent type (meaning we're reachable in some way), we first
                // attempt to narrow the antecedent type. If that produces the never type, and if
                // the antecedent type is incomplete (i.e. a transient type in a loop), then we
                // take the type guard as an indication that control *could* reach here once we
                // have the complete type. We proceed by switching to the silent never type which
                // doesn't report errors when operators are applied to it. Note that this is the
                // *only* place a silent never type is ever generated.
                const assumeTrue = (flow.flags & FlowFlags.TrueCondition) !== 0;
                const nonEvolvingType = finalizeEvolvingArrayType(type);
                const narrowedType = narrowType(nonEvolvingType, flow.expression, assumeTrue);
                if (narrowedType === nonEvolvingType) {
                    return flowType;
                }
                const incomplete = isIncomplete(flowType);
                const resultType = incomplete && narrowedType.flags & TypeFlags.Never ? silentNeverType : narrowedType;
                return createFlowType(resultType, incomplete);
            }

            function getTypeAtSwitchClause(flow: FlowSwitchClause): FlowType {
                const expr = flow.switchStatement.expression;
                const flowType = getTypeAtFlowNode(flow.antecedent);
                let type = getTypeFromFlowType(flowType);
                if (isMatchingReference(reference, expr)) {
                    type = narrowTypeBySwitchOnDiscriminant(type, flow.switchStatement, flow.clauseStart, flow.clauseEnd);
                }
                else if (isMatchingReferenceDiscriminant(expr, type)) {
                    type = narrowTypeByDiscriminant(
                        type,
                        expr as AccessExpression,
                        t => narrowTypeBySwitchOnDiscriminant(t, flow.switchStatement, flow.clauseStart, flow.clauseEnd));
                }
                else if (expr.kind === SyntaxKind.TypeOfExpression && isMatchingReference(reference, (expr as TypeOfExpression).expression)) {
                    type = narrowBySwitchOnTypeOf(type, flow.switchStatement, flow.clauseStart, flow.clauseEnd);
                }
                else if (containsMatchingReferenceDiscriminant(reference, expr)) {
                    type = declaredType;
                }
                return createFlowType(type, isIncomplete(flowType));
            }

            function getTypeAtFlowBranchLabel(flow: FlowLabel): FlowType {
                const antecedentTypes: Type[] = [];
                let subtypeReduction = false;
                let seenIncomplete = false;
                for (const antecedent of flow.antecedents!) {
                    if (antecedent.flags & FlowFlags.PreFinally && (<PreFinallyFlow>antecedent).lock.locked) {
                        // if flow correspond to branch from pre-try to finally and this branch is locked - this means that
                        // we initially have started following the flow outside the finally block.
                        // in this case we should ignore this branch.
                        continue;
                    }
                    const flowType = getTypeAtFlowNode(antecedent);
                    const type = getTypeFromFlowType(flowType);
                    // If the type at a particular antecedent path is the declared type and the
                    // reference is known to always be assigned (i.e. when declared and initial types
                    // are the same), there is no reason to process more antecedents since the only
                    // possible outcome is subtypes that will be removed in the final union type anyway.
                    if (type === declaredType && declaredType === initialType) {
                        return type;
                    }
                    pushIfUnique(antecedentTypes, type);
                    // If an antecedent type is not a subset of the declared type, we need to perform
                    // subtype reduction. This happens when a "foreign" type is injected into the control
                    // flow using the instanceof operator or a user defined type predicate.
                    if (!isTypeSubsetOf(type, declaredType)) {
                        subtypeReduction = true;
                    }
                    if (isIncomplete(flowType)) {
                        seenIncomplete = true;
                    }
                }
                return createFlowType(getUnionOrEvolvingArrayType(antecedentTypes, subtypeReduction ? UnionReduction.Subtype : UnionReduction.Literal), seenIncomplete);
            }

            function getTypeAtFlowLoopLabel(flow: FlowLabel): FlowType {
                // If we have previously computed the control flow type for the reference at
                // this flow loop junction, return the cached type.
                const id = getFlowNodeId(flow);
                const cache = flowLoopCaches[id] || (flowLoopCaches[id] = createMap<Type>());
                const key = getOrSetCacheKey();
                if (!key) {
                    // No cache key is generated when binding patterns are in unnarrowable situations
                    return declaredType;
                }
                const cached = cache.get(key);
                if (cached) {
                    return cached;
                }
                // If this flow loop junction and reference are already being processed, return
                // the union of the types computed for each branch so far, marked as incomplete.
                // It is possible to see an empty array in cases where loops are nested and the
                // back edge of the outer loop reaches an inner loop that is already being analyzed.
                // In such cases we restart the analysis of the inner loop, which will then see
                // a non-empty in-process array for the outer loop and eventually terminate because
                // the first antecedent of a loop junction is always the non-looping control flow
                // path that leads to the top.
                for (let i = flowLoopStart; i < flowLoopCount; i++) {
                    if (flowLoopNodes[i] === flow && flowLoopKeys[i] === key && flowLoopTypes[i].length) {
                        return createFlowType(getUnionOrEvolvingArrayType(flowLoopTypes[i], UnionReduction.Literal), /*incomplete*/ true);
                    }
                }
                // Add the flow loop junction and reference to the in-process stack and analyze
                // each antecedent code path.
                const antecedentTypes: Type[] = [];
                let subtypeReduction = false;
                let firstAntecedentType: FlowType | undefined;
                for (const antecedent of flow.antecedents!) {
                    let flowType;
                    if (!firstAntecedentType) {
                        // The first antecedent of a loop junction is always the non-looping control
                        // flow path that leads to the top.
                        flowType = firstAntecedentType = getTypeAtFlowNode(antecedent);
                    }
                    else {
                        // All but the first antecedent are the looping control flow paths that lead
                        // back to the loop junction. We track these on the flow loop stack.
                        flowLoopNodes[flowLoopCount] = flow;
                        flowLoopKeys[flowLoopCount] = key;
                        flowLoopTypes[flowLoopCount] = antecedentTypes;
                        flowLoopCount++;
                        flowType = getTypeAtFlowNode(antecedent);
                        flowLoopCount--;
                        // If we see a value appear in the cache it is a sign that control flow analysis
                        // was restarted and completed by checkExpressionCached. We can simply pick up
                        // the resulting type and bail out.
                        const cached = cache.get(key);
                        if (cached) {
                            return cached;
                        }
                    }
                    const type = getTypeFromFlowType(flowType);
                    pushIfUnique(antecedentTypes, type);
                    // If an antecedent type is not a subset of the declared type, we need to perform
                    // subtype reduction. This happens when a "foreign" type is injected into the control
                    // flow using the instanceof operator or a user defined type predicate.
                    if (!isTypeSubsetOf(type, declaredType)) {
                        subtypeReduction = true;
                    }
                    // If the type at a particular antecedent path is the declared type there is no
                    // reason to process more antecedents since the only possible outcome is subtypes
                    // that will be removed in the final union type anyway.
                    if (type === declaredType) {
                        break;
                    }
                }
                // The result is incomplete if the first antecedent (the non-looping control flow path)
                // is incomplete.
                const result = getUnionOrEvolvingArrayType(antecedentTypes, subtypeReduction ? UnionReduction.Subtype : UnionReduction.Literal);
                if (isIncomplete(firstAntecedentType!)) {
                    return createFlowType(result, /*incomplete*/ true);
                }
                cache.set(key, result);
                return result;
            }

            function isMatchingReferenceDiscriminant(expr: Expression, computedType: Type) {
                if (!(computedType.flags & TypeFlags.Union) || !isAccessExpression(expr)) {
                    return false;
                }
                const name = getAccessedPropertyName(expr);
                if (name === undefined) {
                    return false;
                }
                return isMatchingReference(reference, expr.expression) && isDiscriminantProperty(computedType, name);
            }

            function narrowTypeByDiscriminant(type: Type, access: AccessExpression, narrowType: (t: Type) => Type): Type {
                const propName = getAccessedPropertyName(access);
                if (propName === undefined) {
                    return type;
                }
                const propType = getTypeOfPropertyOfType(type, propName);
                const narrowedPropType = propType && narrowType(propType);
                return propType === narrowedPropType ? type : filterType(type, t => isTypeComparableTo(getTypeOfPropertyOrIndexSignature(t, propName), narrowedPropType!));
            }

            function narrowTypeByTruthiness(type: Type, expr: Expression, assumeTrue: boolean): Type {
                if (isMatchingReference(reference, expr)) {
                    return getTypeWithFacts(type, assumeTrue ? TypeFacts.Truthy : TypeFacts.Falsy);
                }
                if (isMatchingReferenceDiscriminant(expr, declaredType)) {
                    return narrowTypeByDiscriminant(type, <AccessExpression>expr, t => getTypeWithFacts(t, assumeTrue ? TypeFacts.Truthy : TypeFacts.Falsy));
                }
                if (containsMatchingReferenceDiscriminant(reference, expr)) {
                    return declaredType;
                }
                return type;
            }

            function isTypePresencePossible(type: Type, propName: __String, assumeTrue: boolean) {
                if (getIndexInfoOfType(type, IndexKind.String)) {
                    return true;
                }
                const prop = getPropertyOfType(type, propName);
                if (prop) {
                    return prop.flags & SymbolFlags.Optional ? true : assumeTrue;
                }
                return !assumeTrue;
            }

            function narrowByInKeyword(type: Type, literal: LiteralExpression, assumeTrue: boolean) {
                if (type.flags & (TypeFlags.Union | TypeFlags.Object) || isThisTypeParameter(type)) {
                    const propName = escapeLeadingUnderscores(literal.text);
                    return filterType(type, t => isTypePresencePossible(t, propName, assumeTrue));
                }
                return type;
            }

            function narrowTypeByBinaryExpression(type: Type, expr: BinaryExpression, assumeTrue: boolean): Type {
                switch (expr.operatorToken.kind) {
                    case SyntaxKind.EqualsToken:
                        return narrowTypeByTruthiness(narrowType(type, expr.right, assumeTrue), expr.left, assumeTrue);
                    case SyntaxKind.EqualsEqualsToken:
                    case SyntaxKind.ExclamationEqualsToken:
                    case SyntaxKind.EqualsEqualsEqualsToken:
                    case SyntaxKind.ExclamationEqualsEqualsToken:
                        const operator = expr.operatorToken.kind;
                        const left = getReferenceCandidate(expr.left);
                        const right = getReferenceCandidate(expr.right);
                        if (left.kind === SyntaxKind.TypeOfExpression && isStringLiteralLike(right)) {
                            return narrowTypeByTypeof(type, <TypeOfExpression>left, operator, right, assumeTrue);
                        }
                        if (right.kind === SyntaxKind.TypeOfExpression && isStringLiteralLike(left)) {
                            return narrowTypeByTypeof(type, <TypeOfExpression>right, operator, left, assumeTrue);
                        }
                        if (isMatchingReference(reference, left)) {
                            return narrowTypeByEquality(type, operator, right, assumeTrue);
                        }
                        if (isMatchingReference(reference, right)) {
                            return narrowTypeByEquality(type, operator, left, assumeTrue);
                        }
                        if (isMatchingReferenceDiscriminant(left, declaredType)) {
                            return narrowTypeByDiscriminant(type, <AccessExpression>left, t => narrowTypeByEquality(t, operator, right, assumeTrue));
                        }
                        if (isMatchingReferenceDiscriminant(right, declaredType)) {
                            return narrowTypeByDiscriminant(type, <AccessExpression>right, t => narrowTypeByEquality(t, operator, left, assumeTrue));
                        }
                        if (containsMatchingReferenceDiscriminant(reference, left) || containsMatchingReferenceDiscriminant(reference, right)) {
                            return declaredType;
                        }
                        break;
                    case SyntaxKind.InstanceOfKeyword:
                        return narrowTypeByInstanceof(type, expr, assumeTrue);
                    case SyntaxKind.InKeyword:
                        const target = getReferenceCandidate(expr.right);
                        if (isStringLiteralLike(expr.left) && isMatchingReference(reference, target)) {
                            return narrowByInKeyword(type, expr.left, assumeTrue);
                        }
                        break;
                    case SyntaxKind.CommaToken:
                        return narrowType(type, expr.right, assumeTrue);
                }
                return type;
            }

            function narrowTypeByEquality(type: Type, operator: SyntaxKind, value: Expression, assumeTrue: boolean): Type {
                if (type.flags & TypeFlags.Any) {
                    return type;
                }
                if (operator === SyntaxKind.ExclamationEqualsToken || operator === SyntaxKind.ExclamationEqualsEqualsToken) {
                    assumeTrue = !assumeTrue;
                }
                const valueType = getTypeOfExpression(value);
                if ((type.flags & TypeFlags.Unknown) && assumeTrue && (operator === SyntaxKind.EqualsEqualsEqualsToken || operator === SyntaxKind.ExclamationEqualsEqualsToken)) {
                    if (valueType.flags & (TypeFlags.Primitive | TypeFlags.NonPrimitive)) {
                        return valueType;
                    }
                    if (valueType.flags & TypeFlags.Object) {
                        return nonPrimitiveType;
                    }
                    return type;
                }
                if (valueType.flags & TypeFlags.Nullable) {
                    if (!strictNullChecks) {
                        return type;
                    }
                    const doubleEquals = operator === SyntaxKind.EqualsEqualsToken || operator === SyntaxKind.ExclamationEqualsToken;
                    const facts = doubleEquals ?
                        assumeTrue ? TypeFacts.EQUndefinedOrNull : TypeFacts.NEUndefinedOrNull :
                        valueType.flags & TypeFlags.Null ?
                            assumeTrue ? TypeFacts.EQNull : TypeFacts.NENull :
                            assumeTrue ? TypeFacts.EQUndefined : TypeFacts.NEUndefined;
                    return getTypeWithFacts(type, facts);
                }
                if (type.flags & TypeFlags.NotUnionOrUnit) {
                    return type;
                }
                if (assumeTrue) {
                    const filterFn: (t: Type) => boolean = operator === SyntaxKind.EqualsEqualsToken ?
                        (t => areTypesComparable(t, valueType) || isCoercibleUnderDoubleEquals(t, valueType)) :
                        t => areTypesComparable(t, valueType);
                    const narrowedType = filterType(type, filterFn);
                    return narrowedType.flags & TypeFlags.Never ? type : replacePrimitivesWithLiterals(narrowedType, valueType);
                }
                if (isUnitType(valueType)) {
                    const regularType = getRegularTypeOfLiteralType(valueType);
                    return filterType(type, t => getRegularTypeOfLiteralType(t) !== regularType);
                }
                return type;
            }

            function narrowTypeByTypeof(type: Type, typeOfExpr: TypeOfExpression, operator: SyntaxKind, literal: LiteralExpression, assumeTrue: boolean): Type {
                // We have '==', '!=', '===', or !==' operator with 'typeof xxx' and string literal operands
                const target = getReferenceCandidate(typeOfExpr.expression);
                if (!isMatchingReference(reference, target)) {
                    // For a reference of the form 'x.y', a 'typeof x === ...' type guard resets the
                    // narrowed type of 'y' to its declared type.
                    if (containsMatchingReference(reference, target)) {
                        return declaredType;
                    }
                    return type;
                }
                if (operator === SyntaxKind.ExclamationEqualsToken || operator === SyntaxKind.ExclamationEqualsEqualsToken) {
                    assumeTrue = !assumeTrue;
                }
                if (type.flags & TypeFlags.Any && literal.text === "function") {
                    return type;
                }
                const facts = assumeTrue ?
                    typeofEQFacts.get(literal.text) || TypeFacts.TypeofEQHostObject :
                    typeofNEFacts.get(literal.text) || TypeFacts.TypeofNEHostObject;
                return getTypeWithFacts(assumeTrue ? mapType(type, narrowTypeForTypeof) : type, facts);

                function narrowTypeForTypeof(type: Type) {
                    if (type.flags & TypeFlags.Unknown && literal.text === "object") {
                        return getUnionType([nonPrimitiveType, nullType]);
                    }
                    // We narrow a non-union type to an exact primitive type if the non-union type
                    // is a supertype of that primitive type. For example, type 'any' can be narrowed
                    // to one of the primitive types.
                    const targetType = literal.text === "function" ? globalFunctionType : typeofTypesByName.get(literal.text);
                    if (targetType) {
                        if (isTypeSubtypeOf(type, targetType)) {
                            return type;
                        }
                        if (isTypeSubtypeOf(targetType, type)) {
                            return targetType;
                        }
                        if (type.flags & TypeFlags.Instantiable) {
                            const constraint = getBaseConstraintOfType(type) || anyType;
                            if (isTypeSubtypeOf(targetType, constraint)) {
                                return getIntersectionType([type, targetType]);
                            }
                        }
                    }
                    return type;
                }
            }

            function narrowTypeBySwitchOnDiscriminant(type: Type, switchStatement: SwitchStatement, clauseStart: number, clauseEnd: number) {
                // We only narrow if all case expressions specify
                // values with unit types, except for the case where
                // `type` is unknown. In this instance we map object
                // types to the nonPrimitive type and narrow with that.
                const switchTypes = getSwitchClauseTypes(switchStatement);
                if (!switchTypes.length) {
                    return type;
                }
                const clauseTypes = switchTypes.slice(clauseStart, clauseEnd);
                const hasDefaultClause = clauseStart === clauseEnd || contains(clauseTypes, neverType);
                if ((type.flags & TypeFlags.Unknown) && !hasDefaultClause) {
                    let groundClauseTypes: Type[] | undefined;
                    for (let i = 0; i < clauseTypes.length; i += 1) {
                        const t = clauseTypes[i];
                        if (t.flags & (TypeFlags.Primitive | TypeFlags.NonPrimitive)) {
                            if (groundClauseTypes !== undefined) {
                                groundClauseTypes.push(t);
                            }
                        }
                        else if (t.flags & TypeFlags.Object) {
                            if (groundClauseTypes === undefined) {
                                groundClauseTypes = clauseTypes.slice(0, i);
                            }
                            groundClauseTypes.push(nonPrimitiveType);
                        }
                        else {
                            return type;
                        }
                    }
                    return getUnionType(groundClauseTypes === undefined ? clauseTypes : groundClauseTypes);
                }
                const discriminantType = getUnionType(clauseTypes);
                const caseType =
                    discriminantType.flags & TypeFlags.Never ? neverType :
                    replacePrimitivesWithLiterals(filterType(type, t => areTypesComparable(discriminantType, t)), discriminantType);
                if (!hasDefaultClause) {
                    return caseType;
                }
                const defaultType = filterType(type, t => !(isUnitType(t) && contains(switchTypes, getRegularTypeOfLiteralType(t))));
                return caseType.flags & TypeFlags.Never ? defaultType : getUnionType([caseType, defaultType]);
            }

            function getImpliedTypeFromTypeofCase(type: Type, text: string) {
                switch (text) {
                    case "function":
                        return type.flags & TypeFlags.Any ? type : globalFunctionType;
                    case "object":
                        return type.flags & TypeFlags.Unknown ? getUnionType([nonPrimitiveType, nullType]) : type;
                    default:
                        return typeofTypesByName.get(text) || type;
                }
            }

            function narrowTypeForTypeofSwitch(candidate: Type) {
                return (type: Type) => {
                    if (isTypeSubtypeOf(candidate, type)) {
                        return candidate;
                    }
                    if (type.flags & TypeFlags.Instantiable) {
                        const constraint = getBaseConstraintOfType(type) || anyType;
                        if (isTypeSubtypeOf(candidate, constraint)) {
                            return getIntersectionType([type, candidate]);
                        }
                    }
                    return type;
                };
            }

            function narrowBySwitchOnTypeOf(type: Type, switchStatement: SwitchStatement, clauseStart: number, clauseEnd: number): Type {
                const switchWitnesses = getSwitchClauseTypeOfWitnesses(switchStatement);
                if (!switchWitnesses.length) {
                    return type;
                }
                //  Equal start and end denotes implicit fallthrough; undefined marks explicit default clause
                const defaultCaseLocation = findIndex(switchWitnesses, elem => elem === undefined);
                const hasDefaultClause = clauseStart === clauseEnd || (defaultCaseLocation >= clauseStart && defaultCaseLocation < clauseEnd);
                let clauseWitnesses: string[];
                let switchFacts: TypeFacts;
                if (defaultCaseLocation > -1) {
                    // We no longer need the undefined denoting an
                    // explicit default case. Remove the undefined and
                    // fix-up clauseStart and clauseEnd.  This means
                    // that we don't have to worry about undefined
                    // in the witness array.
                    const witnesses = <string[]>switchWitnesses.filter(witness => witness !== undefined);
                    // The adjusted clause start and end after removing the `default` statement.
                    const fixedClauseStart = defaultCaseLocation < clauseStart ? clauseStart - 1 : clauseStart;
                    const fixedClauseEnd = defaultCaseLocation < clauseEnd ? clauseEnd - 1 : clauseEnd;
                    clauseWitnesses = witnesses.slice(fixedClauseStart, fixedClauseEnd);
                    switchFacts = getFactsFromTypeofSwitch(fixedClauseStart, fixedClauseEnd, witnesses, hasDefaultClause);
                }
                else {
                    clauseWitnesses = <string[]>switchWitnesses.slice(clauseStart, clauseEnd);
                    switchFacts = getFactsFromTypeofSwitch(clauseStart, clauseEnd, <string[]>switchWitnesses, hasDefaultClause);
                }
                if (hasDefaultClause) {
                    return filterType(type, t => (getTypeFacts(t) & switchFacts) === switchFacts);
                }
                /*
                  The implied type is the raw type suggested by a
                  value being caught in this clause.

                  When the clause contains a default case we ignore
                  the implied type and try to narrow using any facts
                  we can learn: see `switchFacts`.

                  Example:
                  switch (typeof x) {
                      case 'number':
                      case 'string': break;
                      default: break;
                      case 'number':
                      case 'boolean': break
                  }

                  In the first clause (case `number` and `string`) the
                  implied type is number | string.

                  In the default clause we de not compute an implied type.

                  In the third clause (case `number` and `boolean`)
                  the naive implied type is number | boolean, however
                  we use the type facts to narrow the implied type to
                  boolean. We know that number cannot be selected
                  because it is caught in the first clause.
                */
                let impliedType = getTypeWithFacts(getUnionType(clauseWitnesses.map(text => getImpliedTypeFromTypeofCase(type, text))), switchFacts);
                if (impliedType.flags & TypeFlags.Union) {
                    impliedType = getAssignmentReducedType(impliedType as UnionType, getBaseConstraintOrType(type));
                }
                return getTypeWithFacts(mapType(type, narrowTypeForTypeofSwitch(impliedType)), switchFacts);
            }

            function narrowTypeByInstanceof(type: Type, expr: BinaryExpression, assumeTrue: boolean): Type {
                const left = getReferenceCandidate(expr.left);
                if (!isMatchingReference(reference, left)) {
                    // For a reference of the form 'x.y', an 'x instanceof T' type guard resets the
                    // narrowed type of 'y' to its declared type. We do this because preceding 'x.y'
                    // references might reference a different 'y' property. However, we make an exception
                    // for property accesses where x is a synthetic 'this' expression, indicating that we
                    // were called from isPropertyInitializedInConstructor. Without this exception,
                    // initializations of 'this' properties that occur before a 'this instanceof XXX'
                    // check would not be considered.
                    if (containsMatchingReference(reference, left) && !isSyntheticThisPropertyAccess(reference)) {
                        return declaredType;
                    }
                    return type;
                }

                // Check that right operand is a function type with a prototype property
                const rightType = getTypeOfExpression(expr.right);
                if (!isTypeDerivedFrom(rightType, globalFunctionType)) {
                    return type;
                }

                let targetType: Type | undefined;
                const prototypeProperty = getPropertyOfType(rightType, "prototype" as __String);
                if (prototypeProperty) {
                    // Target type is type of the prototype property
                    const prototypePropertyType = getTypeOfSymbol(prototypeProperty);
                    if (!isTypeAny(prototypePropertyType)) {
                        targetType = prototypePropertyType;
                    }
                }

                // Don't narrow from 'any' if the target type is exactly 'Object' or 'Function'
                if (isTypeAny(type) && (targetType === globalObjectType || targetType === globalFunctionType)) {
                    return type;
                }

                if (!targetType) {
                    const constructSignatures = getSignaturesOfType(rightType, SignatureKind.Construct);
                    targetType = constructSignatures.length ?
                        getUnionType(map(constructSignatures, signature => getReturnTypeOfSignature(getErasedSignature(signature)))) :
                        emptyObjectType;
                }

                return getNarrowedType(type, targetType, assumeTrue, isTypeDerivedFrom);
            }

            function getNarrowedType(type: Type, candidate: Type, assumeTrue: boolean, isRelated: (source: Type, target: Type) => boolean) {
                if (!assumeTrue) {
                    return filterType(type, t => !isRelated(t, candidate));
                }
                // If the current type is a union type, remove all constituents that couldn't be instances of
                // the candidate type. If one or more constituents remain, return a union of those.
                if (type.flags & TypeFlags.Union) {
                    const assignableType = filterType(type, t => isRelated(t, candidate));
                    if (!(assignableType.flags & TypeFlags.Never)) {
                        return assignableType;
                    }
                }
                // If the candidate type is a subtype of the target type, narrow to the candidate type.
                // Otherwise, if the target type is assignable to the candidate type, keep the target type.
                // Otherwise, if the candidate type is assignable to the target type, narrow to the candidate
                // type. Otherwise, the types are completely unrelated, so narrow to an intersection of the
                // two types.
                return isTypeSubtypeOf(candidate, type) ? candidate :
                    isTypeAssignableTo(type, candidate) ? type :
                    isTypeAssignableTo(candidate, type) ? candidate :
                    getIntersectionType([type, candidate]);
            }

            function narrowTypeByTypePredicate(type: Type, callExpression: CallExpression, assumeTrue: boolean): Type {
                if (!hasMatchingArgument(callExpression, reference) || !maybeTypePredicateCall(callExpression)) {
                    return type;
                }
                const signature = getResolvedSignature(callExpression);
                const predicate = getTypePredicateOfSignature(signature);
                if (!predicate) {
                    return type;
                }

                // Don't narrow from 'any' if the predicate type is exactly 'Object' or 'Function'
                if (isTypeAny(type) && (predicate.type === globalObjectType || predicate.type === globalFunctionType)) {
                    return type;
                }

                if (isIdentifierTypePredicate(predicate)) {
                    const predicateArgument = callExpression.arguments[predicate.parameterIndex];
                    if (predicateArgument) {
                        if (isMatchingReference(reference, predicateArgument)) {
                            return getNarrowedType(type, predicate.type, assumeTrue, isTypeSubtypeOf);
                        }
                        if (containsMatchingReference(reference, predicateArgument)) {
                            return declaredType;
                        }
                    }
                }
                else {
                    const invokedExpression = skipParentheses(callExpression.expression);
                    if (isAccessExpression(invokedExpression)) {
                        const possibleReference = skipParentheses(invokedExpression.expression);
                        if (isMatchingReference(reference, possibleReference)) {
                            return getNarrowedType(type, predicate.type, assumeTrue, isTypeSubtypeOf);
                        }
                        if (containsMatchingReference(reference, possibleReference)) {
                            return declaredType;
                        }
                    }
                }
                return type;
            }

            // Narrow the given type based on the given expression having the assumed boolean value. The returned type
            // will be a subtype or the same type as the argument.
            function narrowType(type: Type, expr: Expression, assumeTrue: boolean): Type {
                switch (expr.kind) {
                    case SyntaxKind.Identifier:
                    case SyntaxKind.ThisKeyword:
                    case SyntaxKind.SuperKeyword:
                    case SyntaxKind.PropertyAccessExpression:
                    case SyntaxKind.ElementAccessExpression:
                        return narrowTypeByTruthiness(type, expr, assumeTrue);
                    case SyntaxKind.CallExpression:
                        return narrowTypeByTypePredicate(type, <CallExpression>expr, assumeTrue);
                    case SyntaxKind.ParenthesizedExpression:
                        return narrowType(type, (<ParenthesizedExpression>expr).expression, assumeTrue);
                    case SyntaxKind.BinaryExpression:
                        return narrowTypeByBinaryExpression(type, <BinaryExpression>expr, assumeTrue);
                    case SyntaxKind.PrefixUnaryExpression:
                        if ((<PrefixUnaryExpression>expr).operator === SyntaxKind.ExclamationToken) {
                            return narrowType(type, (<PrefixUnaryExpression>expr).operand, !assumeTrue);
                        }
                        break;
                }
                return type;
            }
        }

function getInitialOrAssignedType(flow: FlowAssignment) {
                const node = flow.node;
                if (flow.flags & FlowFlags.Cached) {
                    const cached = flowAssignmentTypes[getNodeId(node)];
                    if (cached) {
                        return cached;
                    }
                }
                const startInvocationCount = flowInvocationCount;
                const type = getConstraintForLocation(node.kind === SyntaxKind.VariableDeclaration || node.kind === SyntaxKind.BindingElement ?
                    getInitialType(<VariableDeclaration | BindingElement>node) :
                    getAssignedType(node), reference);
                // We cache the assigned type when getFlowTypeOfReference was recursively invoked in the
                // resolution of the assigned type and we're not within loop analysis.
                if (flowInvocationCount !== startInvocationCount && flowLoopCount === flowLoopStart) {
                    flow.flags |= FlowFlags.Cached;
                    flowAssignmentTypes[getNodeId(node)] = type;
                }
                return type;
            }

function getTypeAtFlowAssignment(flow: FlowAssignment) {
                const node = flow.node;
                // Assignments only narrow the computed type if the declared type is a union type. Thus, we
                // only need to evaluate the assigned type if the declared type is a union type.
                if (isMatchingReference(reference, node)) {
                    if (getAssignmentTargetKind(node) === AssignmentKind.Compound) {
                        const flowType = getTypeAtFlowNode(flow.antecedent);
                        return createFlowType(getBaseTypeOfLiteralType(getTypeFromFlowType(flowType)), isIncomplete(flowType));
                    }
                    if (declaredType === autoType || declaredType === autoArrayType) {
                        if (isEmptyArrayAssignment(node)) {
                            return getEvolvingArrayType(neverType);
                        }
                        const assignedType = getBaseTypeOfLiteralType(getInitialOrAssignedType(flow));
                        return isTypeAssignableTo(assignedType, declaredType) ? assignedType : anyArrayType;
                    }
                    if (declaredType.flags & TypeFlags.Union) {
                        return getAssignmentReducedType(<UnionType>declaredType, getInitialOrAssignedType(flow));
                    }
                    return declaredType;
                }
                // We didn't have a direct match. However, if the reference is a dotted name, this
                // may be an assignment to a left hand part of the reference. For example, for a
                // reference 'x.y.z', we may be at an assignment to 'x.y' or 'x'. In that case,
                // return the declared type.
                if (containsMatchingReference(reference, node)) {
                    // A matching dotted name might also be an expando property on a function *expression*,
                    // in which case we continue control flow analysis back to the function's declaration
                    if (isVariableDeclaration(node) && (isInJSFile(node) || isVarConst(node))) {
                        const init = getDeclaredExpandoInitializer(node);
                        if (init && (init.kind === SyntaxKind.FunctionExpression || init.kind === SyntaxKind.ArrowFunction)) {
                            return getTypeAtFlowNode(flow.antecedent);
                        }
                    }
                    return declaredType;
                }
                // for (const _ in ref) acts as a nonnull on ref
                if (isVariableDeclaration(node) && node.parent.parent.kind === SyntaxKind.ForInStatement && isMatchingReference(reference, node.parent.parent.expression)) {
                    return getNonNullableTypeIfNeeded(getTypeFromFlowType(getTypeAtFlowNode(flow.antecedent)));
                }
                // Assignment doesn't affect reference
                return undefined;
            }