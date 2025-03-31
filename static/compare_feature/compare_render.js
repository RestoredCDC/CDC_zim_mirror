/**
 * static/compare_feature/compare_render.js
 *
 * Handles rendering the comparison diff view on the client-side.
 * Reads data embedded in the HTML (original lines, render instructions)
 * and dynamically builds the diff output in the '#diff_result' element.
 * Also manages the word-level highlighting toggle and legend updates.
 */
document.addEventListener("DOMContentLoaded", function () {
    // Let's get started once the page is ready
    console.log("Initializing client-side diff rendering...");

    // --- Grab Handles to DOM Elements We Need ---
    const diffResultElement = document.getElementById("diff_result");
    const inlineToggleCheckbox = document.getElementById(
        "inlineHighlightToggle"
    );
    // Legend description spans (for dynamic text updates)
    const legendRemovedSpan = document.getElementById("legend-removed-desc");
    const legendAddedSpan = document.getElementById("legend-added-desc");
    const legendSameSpan = document.getElementById("legend-same-desc");
    // Note: Injected text legend is static HTML

    // Basic check to make sure our target elements exist
    if (
        !diffResultElement ||
        !inlineToggleCheckbox ||
        !legendRemovedSpan ||
        !legendAddedSpan ||
        !legendSameSpan
    ) {
        console.error(
            "Required DOM elements (diff_result, toggle, legend spans) not found. Cannot render diff."
        );
        if (diffResultElement)
            // Try to display error message
            diffResultElement.textContent =
                "Error: Cannot initialize diff view (missing required HTML elements).";
        return; // Stop execution if elements are missing
    }

    // --- Load Data Embedded by Server ---
    let lines_orig_A = []; // Lines from the archived page
    let lines_orig_B = []; // Lines from the live page
    let render_instructions = []; // Steps from backend difflib on how to build the view
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
        // Basic type validation after parsing
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
        return; // Can't proceed without data
    }

    // --- Helper Functions ---

    // Patterns for special styling (e.g., banners injected by our server)
    const INJECTED_PATTERNS = [
        "restoredcdc", // Check is case-insensitive below
        "RestoredCDC.org is an independent project",
        "RestoredCDC is an archival snapshot",
        "news items and outbreak information are not current",
    ];

    /**
     * Checks if a line contains specific substrings indicating it was injected
     * by the RestoredCDC server (like disclaimers) and shouldn't be diffed normally.
     * @param {string | null} lineText - The text content of the line.
     * @returns {boolean} True if the line matches an injected pattern, false otherwise.
     */
    function checkInject(lineText) {
        if (
            !lineText ||
            typeof lineText !== "string" ||
            INJECTED_PATTERNS.length === 0
        ) {
            return false;
        }
        const lowerLineText = lineText.toLowerCase();
        // Check if any known injected pattern is present
        return INJECTED_PATTERNS.some((pattern) =>
            lowerLineText.includes(pattern.toLowerCase())
        );
    }

    /**
     * Creates the HTML structure for a single line of the diff output.
     * Handles applying CSS classes for styling and preserves leading/trailing whitespace visually.
     * Uses createTextNode for inserting actual content to prevent XSS.
     *
     * @param {string | null} lineText - The raw text content of the line.
     * @param {string} lineClass - CSS class for the container element (e.g., 'line-added', 'line-removed'). Controls background.
     * @param {string} textClass - CSS class for the inner text span (e.g., 'text-added', 'text-removed'). Controls text color/style.
     * @param {string} [baseSemanticType='span'] - The HTML tag type for the main container ('span', 'ins', 'del').
     * @returns {DocumentFragment} A fragment containing the styled line elements.
     */
    function createLineContent(
        lineText,
        lineClass,
        textClass,
        baseSemanticType = "span"
    ) {
        const contentFragment = document.createDocumentFragment();
        const safeLineText = lineText || ""; // Ensure we have a string
        // Separate leading whitespace, main content, and trailing whitespace
        const lineMatch = safeLineText.match(/^(\s*)(.*?)(\s*)$/);
        const leadingWhitespace = lineMatch ? lineMatch[1] : "";
        let lineContent = lineMatch ? lineMatch[2] : safeLineText;
        const trailingWhitespace = lineMatch ? lineMatch[3] : ""; // Fixed typo here

        // Use a non-breaking space if content is empty to maintain line height
        const contentNodeText = lineContent === "" ? "\u00A0" : lineContent;

        // Append leading whitespace as-is
        if (leadingWhitespace) {
            contentFragment.appendChild(
                document.createTextNode(leadingWhitespace)
            );
        }

        // Create the main wrapper (span/ins/del) which often holds the background
        const contentElement = document.createElement(baseSemanticType);
        contentElement.className = lineClass;

        // Create an inner span for the text itself, gets the text color/style class
        const textSpan = document.createElement("span");
        textSpan.className = textClass;
        textSpan.appendChild(document.createTextNode(contentNodeText)); // Safely add text content

        contentElement.appendChild(textSpan);
        contentFragment.appendChild(contentElement);

        // Append trailing whitespace as-is
        if (trailingWhitespace) {
            contentFragment.appendChild(
                document.createTextNode(trailingWhitespace)
            );
        }
        return contentFragment;
    }

    /**
     * Updates the text content of the legend items based on whether
     * word-level highlighting is currently enabled.
     */
    function updateLegend() {
        const isWordLevel = inlineToggleCheckbox.checked;
        console.log(
            "Updating legend explanation. Word level enabled:",
            isWordLevel
        );

        // Colors defined in CSS/HTML styles
        const removedColor = "#ee0000";
        const addedColor = "#009900";
        const sameColor = "#333";

        // Use innerHTML to include the strong tag for the colored label part
        if (isWordLevel) {
            legendRemovedSpan.innerHTML = `<strong style="color: ${removedColor};">Removed:</strong> Line removed from cdc.gov. Specific word removals are <strong style="color: ${removedColor};">red.</strong>`;
            legendAddedSpan.innerHTML = `<strong style="color: ${addedColor};">Added:</strong> Line added to cdc.gov. Specific word additions are <strong style="color: ${addedColor};">green.</strong>`;
            legendSameSpan.innerHTML = `<strong style="color: ${sameColor};">Unchanged:</strong> Line unchanged.`;
        } else {
            legendRemovedSpan.innerHTML = `<strong style="color: ${removedColor};">Removed:</strong> Line removed from cdc.gov.`;
            legendAddedSpan.innerHTML = `<strong style="color: ${addedColor};">Added:</strong> Line added to cdc.gov.`;
            legendSameSpan.innerHTML = `<strong style="color: ${sameColor};">Unchanged:</strong> Line unchanged.`;
        }
        // The 'Injected' legend item is static HTML, no need to update it here
    }

    /**
     * The main function to render the entire diff view.
     * Clears previous results and rebuilds the content based on
     * render_instructions and the state of the inline highlighting toggle.
     */
    function renderDiffView() {
        console.log("Starting full diff render...");
        diffResultElement.innerHTML = ""; // Clear previous diff
        const fragment = document.createDocumentFragment(); // Build new diff off-DOM
        const inlineHighlightingEnabled = inlineToggleCheckbox.checked;
        console.log(
            "Inline (Word-Level) Highlighting Enabled:",
            inlineHighlightingEnabled
        );

        // Handle case where backend processing yielded no instructions (e.g., identical files)
        if (
            render_instructions.length === 0 &&
            lines_orig_A.length > 0 &&
            lines_orig_B.length > 0
        ) {
            console.log(
                "No render instructions found, indicating no differences."
            );
            const noDiffDiv = document.createElement("div");
            noDiffDiv.className = "diff-line"; // Reuse class for basic styling
            noDiffDiv.style.fontStyle = "italic";
            noDiffDiv.textContent =
                "No textual differences found (ignoring whitespace and filtered elements).";
            fragment.appendChild(noDiffDiv);
        } else if (
            render_instructions.length === 0 &&
            (lines_orig_A.length === 0 || lines_orig_B.length === 0)
        ) {
            // Handle cases where one/both inputs were effectively empty after processing
            console.warn(
                "Render instructions empty and one or both source contents are empty."
            );
            // Optionally display a message here, or rely on backend error reporting.
        }

        // Process each instruction from the backend difflib
        render_instructions.forEach((instruction, instructionIndex) => {
            let original_line_A = null; // Line from archived page (if relevant)
            let original_line_B = null; // Line from live page (if relevant)
            let line_idx_a = instruction.line_index_a;
            let line_idx_b = instruction.line_index_b;
            const baseType = instruction.type; // 'added', 'removed', 'unchanged', 'replace'
            let proceed = true;

            // Safely retrieve the original line text based on the instruction
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
                // Skip instruction if index was invalid
                console.warn(
                    `Skipping instruction index ${instructionIndex} due to invalid line index.`
                );
                return;
            }

            // Filter out lines that only contain whitespace for display purposes
            // (Backend diff ignores leading/trailing, but we hide purely blank lines unless part of a replace)
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

            // Skip rendering if it's a non-replace operation on a blank line
            if (baseType === "unchanged" && isBBlank) return;
            if (baseType === "added" && isBBlank) return;
            if (baseType === "removed" && isABlank) return;
            // Skip replace only if BOTH sides are effectively blank
            if (baseType === "replace" && isABlank && isBBlank) return;

            // --- Render Based on Instruction Type ---
            if (baseType === "replace") {
                // Render both lines (A then B) with potential word-level diff
                const isInjectA = checkInject(original_line_A);
                const isInjectB = checkInject(original_line_B);

                // --- Render Line A (Removed/Old) ---
                const lineDivA = document.createElement("div");
                lineDivA.className = "diff-line";
                if (isInjectA) {
                    // Handle injected content styling
                    lineDivA.appendChild(
                        createLineContent(
                            original_line_A,
                            "line-injected",
                            "text-unchanged",
                            "span"
                        )
                    );
                } else {
                    // Use word-level diff only if enabled AND both sides have actual content
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
                        contentSpanA.className = "line-removed"; // Red background span
                        const contentB =
                            ((original_line_B || "").match(
                                /^(\s*)(.*?)(\s*)$/
                            ) || [])[2] ||
                            original_line_B ||
                            "";
                        const wordDiff = Diff.diffWordsWithSpace(
                            contentA,
                            contentB
                        ); // External jsdiff library call

                        // Build inner spans for common/removed words
                        wordDiff.forEach((part) => {
                            if (!part.added) {
                                // Show parts from original A (common or removed)
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
                        // Handle cases where the result might be empty (e.g., only whitespace diff)
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
                        // Word highlighting disabled or one side blank, render as simple removal
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
                fragment.appendChild(lineDivA); // Add Line A to the fragment

                // --- Render Line B (Added/New) ---
                const lineDivB = document.createElement("div");
                lineDivB.className = "diff-line";
                if (isInjectB) {
                    // Handle injected content styling
                    lineDivB.appendChild(
                        createLineContent(
                            original_line_B,
                            "line-injected",
                            "text-unchanged",
                            "span"
                        )
                    );
                } else {
                    // --- Scope fix: Declare contentSpanB outside the next if ---
                    let contentSpanB = null;

                    if (inlineHighlightingEnabled && !isABlank && !isBBlank) {
                        // Word diff block START
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

                        // Assign the variable declared outside
                        contentSpanB = document.createElement("span");
                        contentSpanB.className = "line-added"; // Green background span

                        const contentA =
                            ((original_line_A || "").match(
                                /^(\s*)(.*?)(\s*)$/
                            ) || [])[2] ||
                            original_line_A ||
                            "";
                        const wordDiff = Diff.diffWordsWithSpace(
                            contentA,
                            contentB
                        ); // jsdiff call

                        // Build inner spans for common/added words
                        wordDiff.forEach((part) => {
                            if (!part.removed) {
                                // Show parts from new B (common or added)
                                const wordSpan = document.createElement("span");
                                wordSpan.className = part.added
                                    ? "word-added"
                                    : "word-common"; // Apply specific class
                                const wordText =
                                    part.value === "" ? "\u00A0" : part.value; // Use corrected var name
                                wordSpan.appendChild(
                                    document.createTextNode(wordText)
                                );
                                // Safely append to contentSpanB
                                if (contentSpanB) {
                                    contentSpanB.appendChild(wordSpan);
                                }
                            }
                        });

                        // Handle cases where the result might be empty
                        if (
                            contentSpanB &&
                            contentSpanB.childNodes.length === 0
                        ) {
                            const emptySpan = document.createElement("span");
                            emptySpan.className = "word-added";
                            emptySpan.innerHTML = "&nbsp;";
                            contentSpanB.appendChild(emptySpan);
                        }
                        // Safely append contentSpanB
                        if (contentSpanB) {
                            lineDivB.appendChild(contentSpanB);
                        }
                        if (trailingWhitespaceB)
                            lineDivB.appendChild(
                                document.createTextNode(trailingWhitespaceB)
                            );
                    } else {
                        // Word highlighting disabled or one side blank, render as simple addition
                        lineDivB.appendChild(
                            createLineContent(
                                original_line_B,
                                "line-added",
                                "text-added",
                                "ins"
                            )
                        );
                        // contentSpanB remains null here
                    } // --- End Word diff block ---
                }
                fragment.appendChild(lineDivB); // Add Line B to the fragment
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
                    line_to_render = original_line_B; // Show the 'B' version for unchanged
                    isInject = checkInject(line_to_render);
                }

                // Override styles if it's known injected content
                if (isInject) {
                    lineClass = "line-injected";
                    textClass = "text-unchanged";
                    semanticType = "span";
                }

                // Create and append the styled line
                lineDiv.appendChild(
                    createLineContent(
                        line_to_render,
                        lineClass,
                        textClass,
                        semanticType
                    )
                );
                fragment.appendChild(lineDiv);
            } // --- End Instruction Type Handling ---
        }); // End forEach render_instruction

        // Append the completed diff structure to the DOM
        diffResultElement.appendChild(fragment);
        console.log("Finished rendering diff to DOM.");
    } // End renderDiffView

    // --- Initial Setup ---
    // Render the diff and update the legend when the page loads
    if (
        lines_orig_A.length > 0 ||
        lines_orig_B.length > 0 ||
        render_instructions.length > 0
    ) {
        // Only render if there's potentially something to show
        renderDiffView();
        updateLegend();
    } else {
        // Still update legend even if no data (might show initial state or error indication)
        console.log("No data available to render initial diff.");
        updateLegend();
    }

    // --- Event Listener for Toggle Checkbox ---
    inlineToggleCheckbox.addEventListener("change", function () {
        console.log(
            "Highlight toggle changed. Re-rendering diff and updating legend..."
        );
        renderDiffView(); // Re-render the diff view with new setting
        updateLegend(); // Update the legend explanation
    });
}); // End DOMContentLoaded Listener
