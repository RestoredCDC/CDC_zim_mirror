/**
 * static/compare_feature/compare_render.js
 *
 * Handles rendering the comparison diff view on the client-side.
 * Reads data embedded in the HTML (original lines, render instructions)
 * and dynamically builds the diff output in the '#diff_result' element.
 * Manages the word-level highlighting and high-contrast mode toggles and legend updates.
 */
document.addEventListener("DOMContentLoaded", function () {
    // Let's get started once the page is ready
    console.log("Initializing client-side diff rendering...");

    // --- Grab Handles to DOM Elements We Need ---
    const diffResultElement = document.getElementById("diff_result");
    const inlineToggleCheckbox = document.getElementById(
        "inlineHighlightToggle"
    );
    const highContrastCheckbox = document.getElementById("highContrastToggle");
    const legendRemovedSpan = document.getElementById("legend-removed-desc");
    const legendAddedSpan = document.getElementById("legend-added-desc");
    const legendSameSpan = document.getElementById("legend-same-desc");
    // Note: Injected text legend is static HTML

    // Basic check to make sure our target elements exist
    if (
        !diffResultElement ||
        !inlineToggleCheckbox ||
        !highContrastCheckbox ||
        !legendRemovedSpan ||
        !legendAddedSpan ||
        !legendSameSpan
    ) {
        console.error(
            "Required DOM elements (diff_result, toggles, legend spans) not found. Cannot render diff."
        );
        if (diffResultElement)
            diffResultElement.textContent =
                "Error: Cannot initialize diff view (missing required HTML elements).";
        return; // Stop execution if elements are missing
    }

    // --- Load Data Embedded by Server ---
    let lines_orig_A = [];
    let lines_orig_B = [];
    let render_instructions = [];
    try {
        lines_orig_A = JSON.parse(
            document.getElementById("original-lines-a").textContent
        );
        lines_orig_B = JSON.parse(
            document.getElementById("original-lines-b").textContent
        );
        render_instructions = JSON.parse(
            document.getElementById("render-instructions").textContent
        );
        console.log(
            `Retrieved ${render_instructions.length} render instructions.`
        );
        if (
            !Array.isArray(lines_orig_A) ||
            !Array.isArray(lines_orig_B) ||
            !Array.isArray(render_instructions)
        ) {
            throw new Error("Parsed data is not in the expected array format.");
        }
    } catch (e) {
        console.error("Error parsing embedded JSON data:", e);
        diffResultElement.textContent =
            "Error: Could not load or parse comparison data from page.";
        return;
    }

    // --- Helper Functions ---

    const INJECTED_PATTERNS = [
        "restoredcdc",
        "RestoredCDC.org is an independent project",
        "RestoredCDC is an archival snapshot",
        "news items and outbreak information are not current",
    ];

    function checkInject(lineText) {
        if (
            !lineText ||
            typeof lineText !== "string" ||
            INJECTED_PATTERNS.length === 0
        ) {
            return false;
        }
        const lowerLineText = lineText.toLowerCase();
        return INJECTED_PATTERNS.some((pattern) =>
            lowerLineText.includes(pattern.toLowerCase())
        );
    }

    function createLineContent(
        lineText,
        lineClass,
        textClass,
        baseSemanticType = "span"
    ) {
        const contentFragment = document.createDocumentFragment();
        const safeLineText = lineText || "";
        const lineMatch = safeLineText.match(/^(\s*)(.*?)(\s*)$/);
        const leadingWhitespace = lineMatch ? lineMatch[1] : "";
        let lineContent = lineMatch ? lineMatch[2] : safeLineText;
        const trailingWhitespace = lineMatch ? lineMatch[3] : "";
        const contentNodeText = lineContent === "" ? "\u00A0" : lineContent;

        if (leadingWhitespace) {
            contentFragment.appendChild(
                document.createTextNode(leadingWhitespace)
            );
        }
        const contentElement = document.createElement(baseSemanticType);
        contentElement.className = lineClass;
        const textSpan = document.createElement("span");
        textSpan.className = textClass;
        textSpan.appendChild(document.createTextNode(contentNodeText));
        contentElement.appendChild(textSpan);
        contentFragment.appendChild(contentElement);
        if (trailingWhitespace) {
            contentFragment.appendChild(
                document.createTextNode(trailingWhitespace)
            );
        }
        return contentFragment;
    }

    /**
     * Updates the text content and colors of the legend items based on the
     * current state of the word-level and high-contrast toggles.
     */
    function updateLegend() {
        const isWordLevel = inlineToggleCheckbox.checked;
        const isHighContrast = highContrastCheckbox.checked;
        console.log(
            "Updating legend. Word level:",
            isWordLevel,
            "High contrast:",
            isHighContrast
        );

        // --- Define Legend Text Colors ---
        // Default theme colors (match CSS)
        const defaultRemovedColor = "#ee0000";
        const defaultAddedColor = "#009900";
        const defaultSameColor = "#333";

        // High contrast theme text colors (MUST match verified CSS --hc variables)
        const hcRemovedColor = "#ffcc99"; // Example: Light Orange
        const hcAddedColor = "#99ddff"; // Example: Light Cyan
        const hcSameColor = "#1a1a1a"; // Example: Near Black (ensure visible on white card)

        // Select the colors to use for the legend text based on current mode
        const currentRemovedColor = isHighContrast
            ? hcRemovedColor
            : defaultRemovedColor;
        const currentAddedColor = isHighContrast
            ? hcAddedColor
            : defaultAddedColor;
        const currentSameColor = isHighContrast
            ? hcSameColor
            : defaultSameColor;

        // --- Update Legend Descriptions ---
        // Use innerHTML for the strong tags; adjust wording for clarity
        if (isWordLevel) {
            legendRemovedSpan.innerHTML = `<strong style="color: ${currentRemovedColor};">Removed:</strong> Line removed from cdc.gov. Specific word removals are <strong style="color: ${currentRemovedColor};">highlighted.</strong>`;
            legendAddedSpan.innerHTML = `<strong style="color: ${currentAddedColor};">Added:</strong> Line added to cdc.gov. Specific word additions are <strong style="color: ${currentAddedColor};">highlighted.</strong>`;
            legendSameSpan.innerHTML = `<strong style="color: ${currentSameColor};">Unchanged:</strong> Line unchanged.`;
        } else {
            legendRemovedSpan.innerHTML = `<strong style="color: ${currentRemovedColor};">Removed:</strong> Line removed from cdc.gov.`;
            legendAddedSpan.innerHTML = `<strong style="color: ${currentAddedColor};">Added:</strong> Line added to cdc.gov.`;
            legendSameSpan.innerHTML = `<strong style="color: ${currentSameColor};">Unchanged:</strong> Line unchanged.`;
        }
        // Note: Injected legend color is static in HTML/CSS for now, could be updated too if needed
        // const hcInjectedColor = "#d0d0d0";
        // const currentInjectedColor = isHighContrast ? hcInjectedColor : "#8b4513";
        // Find the strong tag in legendInjectedSpan and update its style...
    }

    function renderDiffView() {
        console.log("Starting full diff render...");
        diffResultElement.innerHTML = "";
        const fragment = document.createDocumentFragment();
        const inlineHighlightingEnabled = inlineToggleCheckbox.checked;
        console.log("Inline Highlighting Enabled:", inlineHighlightingEnabled);

        if (
            render_instructions.length === 0 &&
            lines_orig_A.length > 0 &&
            lines_orig_B.length > 0
        ) {
            console.log(
                "No render instructions found, indicating no differences."
            );
            const noDiffDiv = document.createElement("div");
            noDiffDiv.className = "diff-line";
            noDiffDiv.style.fontStyle = "italic";
            noDiffDiv.textContent =
                "No textual differences found (ignoring whitespace and filtered elements).";
            fragment.appendChild(noDiffDiv);
        } else if (
            render_instructions.length === 0 &&
            (lines_orig_A.length === 0 || lines_orig_B.length === 0)
        ) {
            console.warn(
                "Render instructions empty and one or both source contents are empty."
            );
        }

        render_instructions.forEach((instruction, instructionIndex) => {
            let original_line_A = null;
            let original_line_B = null;
            let line_idx_a = instruction.line_index_a;
            let line_idx_b = instruction.line_index_b;
            const baseType = instruction.type;
            let proceed = true;

            if (
                baseType === "added" ||
                baseType === "unchanged" ||
                baseType === "replace"
            ) {
                if (
                    line_idx_b !== undefined &&
                    line_idx_b >= 0 &&
                    line_idx_b < lines_orig_B.length
                ) {
                    original_line_B = lines_orig_B[line_idx_b];
                } else {
                    console.error(
                        `Render Error: Invalid index B=${line_idx_b} for type ${baseType}`
                    );
                    proceed = false;
                }
            }
            if (baseType === "removed" || baseType === "replace") {
                if (
                    line_idx_a !== undefined &&
                    line_idx_a >= 0 &&
                    line_idx_a < lines_orig_A.length
                ) {
                    original_line_A = lines_orig_A[line_idx_a];
                } else {
                    console.error(
                        `Render Error: Invalid index A=${line_idx_a} for type ${baseType}`
                    );
                    proceed = false;
                }
            }
            if (!proceed) {
                console.warn(
                    `Skipping instruction index ${instructionIndex} due to invalid line index.`
                );
                return;
            }

            let line_for_blank_check_A =
                baseType === "removed" || baseType === "replace"
                    ? original_line_A
                    : null;
            let line_for_blank_check_B =
                baseType === "added" ||
                baseType === "unchanged" ||
                baseType === "replace"
                    ? original_line_B
                    : null;
            const isABlank =
                line_for_blank_check_A === null ||
                typeof line_for_blank_check_A !== "string" ||
                line_for_blank_check_A.trim() === "";
            const isBBlank =
                line_for_blank_check_B === null ||
                typeof line_for_blank_check_B !== "string" ||
                line_for_blank_check_B.trim() === "";

            if (baseType === "unchanged" && isBBlank) return;
            if (baseType === "added" && isBBlank) return;
            if (baseType === "removed" && isABlank) return;
            if (baseType === "replace" && isABlank && isBBlank) return;

            if (baseType === "replace") {
                const isInjectA = checkInject(original_line_A);
                const isInjectB = checkInject(original_line_B);

                // --- Render Line A (Removed/Old) ---
                const lineDivA = document.createElement("div");
                lineDivA.className = "diff-line";
                if (isInjectA) {
                    lineDivA.appendChild(
                        createLineContent(
                            original_line_A,
                            "line-injected",
                            "text-unchanged",
                            "span"
                        )
                    );
                } else {
                    if (inlineHighlightingEnabled && !isABlank && !isBBlank) {
                        const matchA = (original_line_A || "").match(
                            /^(\s*)(.*?)(\s*)$/
                        );
                        const leadingWhitespaceA = matchA ? matchA[1] : "";
                        const contentA = matchA
                            ? matchA[2]
                            : original_line_A || "";
                        const trailingWhitespaceA = matchA ? matchA[3] : "";
                        if (leadingWhitespaceA)
                            lineDivA.appendChild(
                                document.createTextNode(leadingWhitespaceA)
                            );

                        const contentSpanA = document.createElement("span");
                        contentSpanA.className = "line-removed";
                        const contentB =
                            ((original_line_B || "").match(
                                /^(\s*)(.*?)(\s*)$/
                            ) || [])[2] ||
                            original_line_B ||
                            "";
                        const wordDiff = Diff.diffWordsWithSpace(
                            contentA,
                            contentB
                        );

                        wordDiff.forEach((part) => {
                            if (!part.added) {
                                const wordSpan = document.createElement("span");
                                wordSpan.className = part.removed
                                    ? "word-removed"
                                    : "word-common";
                                const wordText =
                                    part.value === "" ? "\u00A0" : part.value;
                                wordSpan.appendChild(
                                    document.createTextNode(wordText)
                                );
                                contentSpanA.appendChild(wordSpan);
                            }
                        });
                        if (contentSpanA.childNodes.length === 0) {
                            const emptySpan = document.createElement("span");
                            emptySpan.className = "word-removed";
                            emptySpan.innerHTML = "&nbsp;";
                            contentSpanA.appendChild(emptySpan);
                        }
                        lineDivA.appendChild(contentSpanA);
                        if (trailingWhitespaceA)
                            lineDivA.appendChild(
                                document.createTextNode(trailingWhitespaceA)
                            );
                    } else {
                        lineDivA.appendChild(
                            createLineContent(
                                original_line_A,
                                "line-removed",
                                "text-removed",
                                "del"
                            )
                        );
                    }
                }
                fragment.appendChild(lineDivA);

                // --- Render Line B (Added/New) ---
                const lineDivB = document.createElement("div");
                lineDivB.className = "diff-line";
                if (isInjectB) {
                    lineDivB.appendChild(
                        createLineContent(
                            original_line_B,
                            "line-injected",
                            "text-unchanged",
                            "span"
                        )
                    );
                } else {
                    let contentSpanB = null;
                    if (inlineHighlightingEnabled && !isABlank && !isBBlank) {
                        const matchB = (original_line_B || "").match(
                            /^(\s*)(.*?)(\s*)$/
                        );
                        const leadingWhitespaceB = matchB ? matchB[1] : "";
                        const contentB = matchB
                            ? matchB[2]
                            : original_line_B || "";
                        const trailingWhitespaceB = matchB ? matchB[3] : "";
                        if (leadingWhitespaceB)
                            lineDivB.appendChild(
                                document.createTextNode(leadingWhitespaceB)
                            );

                        contentSpanB = document.createElement("span");
                        contentSpanB.className = "line-added";
                        const contentA =
                            ((original_line_A || "").match(
                                /^(\s*)(.*?)(\s*)$/
                            ) || [])[2] ||
                            original_line_A ||
                            "";
                        const wordDiff = Diff.diffWordsWithSpace(
                            contentA,
                            contentB
                        );

                        wordDiff.forEach((part) => {
                            if (!part.removed) {
                                const wordSpan = document.createElement("span");
                                wordSpan.className = part.added
                                    ? "word-added"
                                    : "word-common";
                                const wordText =
                                    part.value === "" ? "\u00A0" : part.value;
                                wordSpan.appendChild(
                                    document.createTextNode(wordText)
                                );
                                contentSpanB.appendChild(wordSpan);
                            }
                        });
                        if (contentSpanB.childNodes.length === 0) {
                            const emptySpan = document.createElement("span");
                            emptySpan.className = "word-added";
                            emptySpan.innerHTML = "&nbsp;";
                            contentSpanB.appendChild(emptySpan);
                        }
                        lineDivB.appendChild(contentSpanB);
                        if (trailingWhitespaceB)
                            lineDivB.appendChild(
                                document.createTextNode(trailingWhitespaceB)
                            );
                    } else {
                        lineDivB.appendChild(
                            createLineContent(
                                original_line_B,
                                "line-added",
                                "text-added",
                                "ins"
                            )
                        );
                    }
                }
                fragment.appendChild(lineDivB);
            } else {
                // --- Handle Simple Added, Removed, Unchanged Lines ---
                const lineDiv = document.createElement("div");
                lineDiv.className = "diff-line";
                let line_to_render = null;
                let isInject = false;
                let lineClass = "line-unchanged";
                let textClass = "text-unchanged";
                let semanticType = "span";

                if (baseType === "added") {
                    line_to_render = original_line_B;
                    isInject = checkInject(line_to_render);
                    if (!isInject) {
                        lineClass = "line-added";
                        textClass = "text-added";
                        semanticType = "ins";
                    }
                } else if (baseType === "removed") {
                    line_to_render = original_line_A;
                    isInject = checkInject(line_to_render);
                    if (!isInject) {
                        lineClass = "line-removed";
                        textClass = "text-removed";
                        semanticType = "del";
                    }
                } else {
                    // unchanged
                    line_to_render = original_line_B;
                    isInject = checkInject(line_to_render);
                }

                // Override styles if it's known injected content
                if (isInject) {
                    lineClass = "line-injected";
                    textClass = "text-unchanged";
                    semanticType = "span";
                }

                lineDiv.appendChild(
                    createLineContent(
                        line_to_render,
                        lineClass,
                        textClass,
                        semanticType
                    )
                );
                fragment.appendChild(lineDiv);
            }
        });

        diffResultElement.appendChild(fragment);
        console.log("Finished rendering diff to DOM.");
    }

    /**
     * Adds/removes the high-contrast-mode class from the body
     * and triggers a legend update.
     */
    function toggleHighContrastMode() {
        if (highContrastCheckbox.checked) {
            document.body.classList.add("high-contrast-mode");
            console.log("High contrast mode enabled.");
        } else {
            document.body.classList.remove("high-contrast-mode");
            console.log("High contrast mode disabled.");
        }
        updateLegend(); // Refresh legend colors based on the new mode
    }

    // --- Initial Setup ---
    if (
        lines_orig_A.length > 0 ||
        lines_orig_B.length > 0 ||
        render_instructions.length > 0
    ) {
        renderDiffView();
        updateLegend(); // Update legend based on default toggle states
    } else {
        console.log("No data available to render initial diff.");
        updateLegend(); // Set initial legend text based on default toggles
    }

    // --- Event Listeners for Toggles ---
    inlineToggleCheckbox.addEventListener("change", function () {
        console.log(
            "Highlight toggle changed. Re-rendering diff and updating legend..."
        );
        renderDiffView();
        updateLegend();
    });

    highContrastCheckbox.addEventListener("change", toggleHighContrastMode);
}); // End DOMContentLoaded Listener
