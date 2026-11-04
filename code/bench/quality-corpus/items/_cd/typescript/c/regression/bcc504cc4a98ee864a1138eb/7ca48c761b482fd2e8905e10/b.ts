// SPDX-License-Identifier: Apache-2.0

function processNode(node: Node, contextNode: Node, nodeStartLine: number, indentation: number, delta: number) {
            if (!rangeOverlapsWithStartEnd(originalRange, node.getStart(sourceFile), node.getEnd())) {
                return;
            }

            var nodeDynamicIndentation = getDynamicIndentation(node, nodeStartLine, indentation, delta);

            var childContextNode = contextNode;

            // if there are any tokens that logically belong to node and interleave child nodes
            // such tokens will be consumed in processChildNode for for the child that follows them
            forEachChild(
                node,
                child => {
                    processChildNode(child, /*inheritedIndentation*/ Constants.Unknown, nodeDynamicIndentation, nodeStartLine, /*isListElement*/ false)
                },
                (nodes: NodeArray<Node>) => {
                    var listStartToken = getOpenTokenForList(node, nodes);
                    var listEndToken = getCloseTokenForOpenToken(listStartToken);

                    var listDynamicIndentation = nodeDynamicIndentation;
                    var startLine = nodeStartLine;

                    if (listStartToken !== SyntaxKind.Unknown) {
                        // introduce a new indentation scope for lists (including list start and end tokens)
                        while (formattingScanner.isOnToken()) {
                            var tokenInfo = formattingScanner.readTokenInfo(node);
                            if (tokenInfo.token.end > nodes.pos) {
                                break;
                            }
                            else if (tokenInfo.token.kind === listStartToken) {
                                // consume list start token
                                startLine = sourceFile.getLineAndCharacterFromPosition(tokenInfo.token.pos).line;
                                var indentation = 
                                    computeIndentation(tokenInfo.token, startLine, Constants.Unknown, node, nodeDynamicIndentation, startLine);

                                listDynamicIndentation = getDynamicIndentation(node, nodeStartLine, indentation.indentation, indentation.delta);
                                consumeTokenAndAdvanceScanner(tokenInfo, node, listDynamicIndentation);
                            }
                            else {
                                // consume any tokens that precede the list as child elements of 'node' using its indentation scope
                                consumeTokenAndAdvanceScanner(tokenInfo, node, nodeDynamicIndentation);
                            }
                        }
                    }

                    var inheritedIndentation = Constants.Unknown;
                    for (var i = 0, len = nodes.length; i < len; ++i) {
                        inheritedIndentation = processChildNode(nodes[i], inheritedIndentation, listDynamicIndentation, startLine, /*isListElement*/ true)
                    }

                    if (listEndToken !== SyntaxKind.Unknown) {
                        if (formattingScanner.isOnToken()) {
                            var tokenInfo = formattingScanner.readTokenInfo(node);
                            if (tokenInfo.token.kind === listEndToken) {
                                // consume list end token
                                consumeTokenAndAdvanceScanner(tokenInfo, node, listDynamicIndentation);
                            }
                        }
                    }
                });

            // proceed any tokens in the node that are located after child nodes
            while (formattingScanner.isOnToken()) {
                var tokenInfo = formattingScanner.readTokenInfo(node);
                if (tokenInfo.token.end > node.end) {
                    break;
                }
                consumeTokenAndAdvanceScanner(tokenInfo, node, nodeDynamicIndentation);
            }

            function processChildNode(
                child: Node,
                inheritedIndentation: number,
                nodeDynamicIndentation: DynamicIndentation,
                parentStartLine: number,
                isListItem: boolean): number {

                var childStartPos = child.getStart(sourceFile);

                var childStart = sourceFile.getLineAndCharacterFromPosition(childStartPos);
                var childIndentationAmount = isListItem
                    ? tryComputeIndentationForListItem(childStartPos, child.end, parentStartLine, originalRange, inheritedIndentation)
                    : Constants.Unknown;

                if (isListItem && childIndentationAmount !== Constants.Unknown) {
                    inheritedIndentation = childIndentationAmount;
                }

                // child node is outside the target range - do not dive inside
                if (!rangeOverlapsWithStartEnd(originalRange, child.pos, child.end)) {
                    return inheritedIndentation;
                }

                if (child.kind === SyntaxKind.Missing) {
                    return inheritedIndentation;
                }

                while (formattingScanner.isOnToken()) {
                    // proceed any parent tokens that are located prior to child.getStart()
                    var tokenInfo = formattingScanner.readTokenInfo(node);
                    if (tokenInfo.token.end > childStartPos) {
                        break;
                    }

                    consumeTokenAndAdvanceScanner(tokenInfo, node, nodeDynamicIndentation);
                }

                if (!formattingScanner.isOnToken()) {
                    return inheritedIndentation;
                }

                if (isToken(child)) {
                    // if child node is a token, it does not impact indentation, proceed it using parent indentation scope rules
                    var tokenInfo = formattingScanner.readTokenInfo(node);
                    Debug.assert(tokenInfo.token.end === child.end);
                    consumeTokenAndAdvanceScanner(tokenInfo, node, nodeDynamicIndentation);
                    return inheritedIndentation;
                }

                var childIndentation = computeIndentation(child, childStart.line, childIndentationAmount, node, nodeDynamicIndentation, parentStartLine);

                processNode(child, childContextNode, childStart.line, childIndentation.indentation, childIndentation.delta);

                childContextNode = node;

                return inheritedIndentation;
            }

            function consumeTokenAndAdvanceScanner(currentTokenInfo: TokenInfo, parent: Node, dynamicIndentation: DynamicIndentation): void {
                Debug.assert(rangeContainsRange(parent, currentTokenInfo.token));

                var lastTriviaWasNewLine = formattingScanner.lastTrailingTriviaWasNewLine();
                var indentToken = false;

                if (currentTokenInfo.leadingTrivia) {
                    processTrivia(currentTokenInfo.leadingTrivia, parent, childContextNode, dynamicIndentation);
                }

                var lineAdded: boolean;
                var isTokenInRange = rangeContainsRange(originalRange, currentTokenInfo.token);

                var tokenStart = sourceFile.getLineAndCharacterFromPosition(currentTokenInfo.token.pos);
                if (isTokenInRange) {
                    // save prevStartLine since processRange will overwrite this value with current ones
                    var prevStartLine = previousRangeStartLine;
                    lineAdded = processRange(currentTokenInfo.token, tokenStart, parent, childContextNode, dynamicIndentation);
                    if (lineAdded !== undefined) {
                        indentToken = lineAdded;
                    }
                    else {
                        indentToken = lastTriviaWasNewLine && tokenStart.line !== prevStartLine;
                    }
                }

                if (currentTokenInfo.trailingTrivia) {
                    processTrivia(currentTokenInfo.trailingTrivia, parent, childContextNode, dynamicIndentation);
                }

                if (indentToken) {
                    var indentNextTokenOrTrivia = true;
                    if (currentTokenInfo.leadingTrivia) {
                        for (var i = 0, len = currentTokenInfo.leadingTrivia.length; i < len; ++i) {
                            var triviaItem = currentTokenInfo.leadingTrivia[i];
                            if (!rangeContainsRange(originalRange, triviaItem)) {
                                continue;
                            }

                            var triviaStartLine = sourceFile.getLineAndCharacterFromPosition(triviaItem.pos).line;
                            switch (triviaItem.kind) {
                                case SyntaxKind.MultiLineCommentTrivia:
                                    var commentIndentation = dynamicIndentation.getIndentationForComment(currentTokenInfo.token.kind);
                                    indentMultilineComment(triviaItem, commentIndentation, /*firstLineIsIndented*/ !indentNextTokenOrTrivia);
                                    indentNextTokenOrTrivia = false;
                                    break;
                                case SyntaxKind.SingleLineCommentTrivia:
                                    if (indentNextTokenOrTrivia) {
                                        var commentIndentation = dynamicIndentation.getIndentationForComment(currentTokenInfo.token.kind);
                                        insertIndentation(triviaItem.pos, commentIndentation, /*lineAdded*/ false);
                                        indentNextTokenOrTrivia = false;
                                    }
                                    break;
                                case SyntaxKind.NewLineTrivia:
                                    indentNextTokenOrTrivia = true;
                                    break;
                            }
                        }
                    }

                    // indent token only if is it is in target range and does not overlap with any error ranges
                    if (isTokenInRange && !rangeContainsError(currentTokenInfo.token)) {
                        var tokenIndentation = dynamicIndentation.getIndentationForToken(tokenStart.line, currentTokenInfo.token.kind);
                        insertIndentation(currentTokenInfo.token.pos, tokenIndentation, lineAdded);
                    }
                }

                formattingScanner.advance();

                childContextNode = parent;
            }
        }