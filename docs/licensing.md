# Open source licensing options for Cue

**Status: decision pending.** This page compares licenses; it does not grant rights to use, copy, modify, or distribute Cue. No `LICENSE` file is present. Before publishing code, confirm that the copyright holders agree and that reused components, dependencies, models, data, and assets permit the intended distribution.

| License | What it permits or requires | Fit for Cue |
| --- | --- | --- |
| [Apache-2.0](https://opensource.org/license/apache-2.0) | Broad use, modification, and commercial distribution; includes an express patent grant and notice requirements. | Good default if the team wants broad adoption, including proprietary products. |
| [MIT](https://opensource.org/license/mit) | Short, permissive terms requiring preservation of the copyright and license notice. | Simple choice for small libraries or examples when the team values minimal conditions. |
| [MPL-2.0](https://opensource.org/license/mpl-2.0) | Changes to covered source files distributed to others remain under MPL; separate files in a larger work may use other terms. Includes a patent grant. | Middle ground if the team wants shared improvements to released files. |
| [AGPL-3.0-only](https://www.gnu.org/licenses/agpl-3.0.en.html) | Strong copyleft that also requires offering corresponding source to users who interact with a modified program over a network. | Consider if the team wants hosted modifications of the released server to remain available. This can limit adoption by some commercial users. |
| [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Attribution license for documentation and other creative material. | An option for standalone docs or artwork. Creative Commons does not recommend CC licenses for software code. |

These are alternatives, not a combined license grant. Copying every license into the root of the repository without a precise scope could leave contributors and users unsure which terms apply.

## Before a public release

1. Choose one license for each component being released, or specify an explicit dual license with an unambiguous choice of terms.
2. Identify the legal copyright holder and secure agreement from all contributors whose work is included.
3. Review dependencies and any reused Insurge code or assets before publishing.
4. Add the chosen license text as `LICENSE`, plus file or directory level notices for exceptions; record third party notices separately.
5. Document which parts of Cue are open source if the hosted service includes private components.

This is a project planning note, not legal advice.
