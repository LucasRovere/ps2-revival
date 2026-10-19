// Ghidra headless post-script: exports the analysed program to plain files.
// Args: <output dir> [names.tsv]. Format: docs/analysis-plan.md#export-format.
// Before exporting, creates functions at vtable targets that analysis missed.
// @category ps2-revival

import java.io.IOException;
import java.io.PrintWriter;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;

import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.decompiler.parallel.DecompilerCallback;
import ghidra.app.decompiler.parallel.ParallelDecompiler;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressIterator;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.util.DefinedStringIterator;
import ghidra.util.task.TaskMonitor;

public class Export extends GhidraScript {

	private static final int DECOMPILE_TIMEOUT_SECONDS = 60;
	// Shorter runs of {word, code pointer} pairs are often ordinary data.
	private static final int MIN_VTABLE_ENTRIES = 3;
	private static final Comparator<Function> BY_ENTRY = Comparator.comparing(Function::getEntryPoint);

	private Path out;
	private int namesApplied;
	private final List<String> decompileFailures = new ArrayList<>();
	private int stringCount;
	private int dataXrefCount;
	private int symbolCount;
	private int vtableCount;
	private int functionsFromVtables;
	private int functionsFromCalls;

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		out = Path.of(args[0]);
		Files.createDirectories(out.resolve("functions"));

		createVtableFunctions();
		if (args.length > 1) {
			applyNames(Path.of(args[1]));
		}
		List<Function> functions = new ArrayList<>();
		currentProgram.getFunctionManager().getFunctions(true).forEach(functions::add);

		exportFunctionIndex(functions);
		exportDisassembly(functions);
		exportPseudocode(functions);
		exportStrings();
		exportDataXrefs();
		exportSymbols();
		writeSummary(functions);
	}

	private void applyNames(Path namesFile) throws Exception {
		for (String line : Files.readAllLines(namesFile, StandardCharsets.UTF_8)) {
			String[] parts = line.split("\t");
			Address addr = toAddr(parts[0]);
			Function f = getFunctionAt(addr);
			if (f != null) {
				f.setName(parts[1], SourceType.USER_DEFINED);
			}
			else {
				createLabel(addr, parts[1], true, SourceType.USER_DEFINED);
			}
			namesApplied++;
		}
	}

	// This toolchain (old GCC / SN Systems) lays vtables out as 8-byte entries {short delta, short index,
	// code pointer}. Methods reached only through them have no direct callers, so auto-analysis never
	// creates them. Targets inside an existing function are left alone (switch tables, odd data).
	private void createVtableFunctions() throws Exception {
		List<Address> created = new ArrayList<>();
		for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
			if (!b.isInitialized() || b.isExecute() || b.isMapped()) {
				continue;
			}
			byte[] bytes = new byte[(int) b.getSize() / 4 * 4];
			b.getBytes(b.getStart(), bytes);
			ByteBuffer buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
			long[] words = new long[bytes.length / 4];
			for (int i = 0; i < words.length; i++) {
				words[i] = buf.getInt(i * 4) & 0xffffffffL;
			}
			for (int phase = 0; phase < 2; phase++) {
				int i = phase;
				while (i + 1 < words.length) {
					int j = i;
					while (j + 1 < words.length && !isCodePointer(words[j]) && isCodePointer(words[j + 1])) {
						j += 2;
					}
					if ((j - i) / 2 >= MIN_VTABLE_ENTRIES) {
						vtableCount++;
						for (int k = i + 1; k < j; k += 2) {
							Address target = toAddr(words[k]);
							if (getFunctionContaining(target) == null && createFunctionAt(target)) {
								created.add(target);
							}
						}
					}
					i = Math.max(j, i + 2);
				}
			}
		}
		functionsFromVtables = created.size();
		while (!created.isEmpty()) {
			List<Address> next = new ArrayList<>();
			for (Address a : created) {
				for (Instruction insn : currentProgram.getListing().getInstructions(getFunctionAt(a).getBody(), true)) {
					if (!insn.getFlowType().isCall()) {
						continue;
					}
					for (Address target : insn.getFlows()) {
						if (getFunctionContaining(target) == null && createFunctionAt(target)) {
							next.add(target);
						}
					}
				}
			}
			functionsFromCalls += next.size();
			created = next;
		}
	}

	private boolean isCodePointer(long word) {
		if (word % 4 != 0 || word < 0x1000) {
			return false;
		}
		MemoryBlock b = getMemoryBlock(toAddr(word));
		return b != null && b.isExecute() && b.isInitialized() && !b.isMapped();
	}

	private boolean createFunctionAt(Address a) {
		disassemble(a);
		return createFunction(a, null) != null;
	}

	private void exportFunctionIndex(List<Function> functions) throws Exception {
		try (PrintWriter w = writer("functions.jsonl")) {
			for (Function f : functions) {
				w.println("{\"addr\":" + quote(hex(f.getEntryPoint())) +
					",\"name\":" + quote(f.getName()) +
					",\"size\":" + f.getBody().getNumAddresses() +
					",\"calls\":" + addrList(f.getCalledFunctions(monitor)) +
					",\"called_by\":" + addrList(f.getCallingFunctions(monitor)) +
					",\"thunk\":" + f.isThunk() +
					",\"library_match\":null}");
			}
		}
	}

	private void exportDisassembly(List<Function> functions) throws Exception {
		for (Function f : functions) {
			try (PrintWriter w = writer("functions/" + fileStem(f) + ".asm")) {
				w.println("// " + f.getName() + " @ " + hex(f.getEntryPoint()));
				for (Instruction insn : currentProgram.getListing().getInstructions(f.getBody(), true)) {
					w.printf("%s  %s  %s%n", hex(insn.getAddress()), bytesHex(insn.getBytes()), insn);
				}
			}
		}
	}

	private void exportPseudocode(List<Function> functions) throws Exception {
		DecompileOptions options = new DecompileOptions();
		options.grabFromProgram(currentProgram);
		DecompilerCallback<Void> callback = new DecompilerCallback<>(currentProgram, decompiler -> {
			decompiler.setOptions(options);
			decompiler.toggleCCode(true);
			decompiler.setSimplificationStyle("decompile");
		}) {
			@Override
			public Void process(DecompileResults results, TaskMonitor m) throws Exception {
				writePseudocode(results);
				return null;
			}
		};
		callback.setTimeout(DECOMPILE_TIMEOUT_SECONDS);
		try {
			ParallelDecompiler.decompileFunctions(callback, functions, monitor);
		}
		finally {
			callback.dispose();
		}
	}

	private void writePseudocode(DecompileResults results) throws IOException {
		Function f = results.getFunction();
		String code = results.decompileCompleted() ? results.getDecompiledFunction().getC() : null;
		if (code == null) {
			synchronized (decompileFailures) {
				decompileFailures.add(hex(f.getEntryPoint()) + " " + results.getErrorMessage().trim());
			}
			code = "// decompile failed: " + results.getErrorMessage().trim() + "\n";
		}
		Files.writeString(out.resolve("functions/" + fileStem(f) + ".c"), code, StandardCharsets.UTF_8);
	}

	private void exportStrings() throws Exception {
		try (PrintWriter w = writer("strings.jsonl")) {
			for (Data s : DefinedStringIterator.forProgram(currentProgram)) {
				Object value = s.getValue();
				// The EE extension maps uncached RAM mirrors (0x20000000, 0x30100000) onto main RAM.
				if (value == null || getMemoryBlock(s.getAddress()).isMapped()) {
					continue;
				}
				w.println("{\"addr\":" + quote(hex(s.getAddress())) +
					",\"string\":" + quote(value.toString()) +
					",\"xrefs\":" + addrList(referencingFunctions(s.getAddress())) + "}");
				stringCount++;
			}
		}
	}

	private void exportDataXrefs() throws Exception {
		ReferenceManager refs = currentProgram.getReferenceManager();
		AddressIterator destinations = refs.getReferenceDestinationIterator(currentProgram.getMemory(), true);
		try (PrintWriter w = writer("data_xrefs.jsonl")) {
			for (Address dest : destinations) {
				if (getInstructionAt(dest) != null) {
					continue;
				}
				Set<Function> users = referencingFunctions(dest);
				if (!users.isEmpty()) {
					w.println("{\"addr\":" + quote(hex(dest)) + ",\"functions\":" + addrList(users) + "}");
					dataXrefCount++;
				}
			}
		}
	}

	private void exportSymbols() throws Exception {
		try (PrintWriter w = writer("symbols.jsonl")) {
			for (Symbol s : currentProgram.getSymbolTable().getAllSymbols(true)) {
				if (s.getSource() == SourceType.DEFAULT || !s.getAddress().isMemoryAddress()) {
					continue;
				}
				w.println("{\"addr\":" + quote(hex(s.getAddress())) +
					",\"name\":" + quote(s.getName(true)) +
					",\"type\":" + quote(s.getSymbolType().toString()) +
					",\"source\":" + quote(s.getSource().toString()) + "}");
				symbolCount++;
			}
		}
	}

	private void writeSummary(List<Function> functions) throws Exception {
		long thunks = functions.stream().filter(Function::isThunk).count();
		try (PrintWriter w = writer("summary.md")) {
			w.println("# " + currentProgram.getName());
			w.println();
			w.println("- Language: `" + currentProgram.getLanguageID() + "`, compiler spec `" +
				currentProgram.getCompilerSpec().getCompilerSpecID() + "`");
			w.println("- Entry point: `" + hex(currentProgram.getSymbolTable()
				.getExternalEntryPointIterator().next()) + "`");
			w.println("- Functions: " + functions.size() + " (" + thunks + " thunks)");
			w.println("- Decompile failures: " + decompileFailures.size());
			w.println("- Strings: " + stringCount);
			w.println("- Data addresses with xrefs: " + dataXrefCount);
			w.println("- Non-default symbols: " + symbolCount);
			w.println("- Names applied from game.json: " + namesApplied);
			w.println("- Vtables found: " + vtableCount + "; functions created this run from their targets: " +
				functionsFromVtables + ", from calls in those: " + functionsFromCalls);
			w.println();
			w.println("## Segments");
			w.println();
			w.println("| Block | Start | End | Size | Perms |");
			w.println("|---|---|---|---|---|");
			for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
				w.printf("| %s | %s | %s | %d | %s%s%s |%n", b.getName(), hex(b.getStart()), hex(b.getEnd()),
					b.getSize(), b.isRead() ? "r" : "-", b.isWrite() ? "w" : "-", b.isExecute() ? "x" : "-");
			}
			if (!decompileFailures.isEmpty()) {
				w.println();
				w.println("## Decompile failures");
				w.println();
				decompileFailures.stream().sorted().forEach(line -> w.println("- " + line));
			}
		}
	}

	private Set<Function> referencingFunctions(Address addr) {
		Set<Function> users = new TreeSet<>(BY_ENTRY);
		for (Reference ref : getReferencesTo(addr)) {
			Function f = getFunctionContaining(ref.getFromAddress());
			if (f != null) {
				users.add(f);
			}
		}
		return users;
	}

	private PrintWriter writer(String name) throws IOException {
		return new PrintWriter(Files.newBufferedWriter(out.resolve(name), StandardCharsets.UTF_8));
	}

	private static String fileStem(Function f) {
		return String.format("%08x", f.getEntryPoint().getOffset());
	}

	private static String hex(Address addr) {
		return String.format("0x%08x", addr.getOffset());
	}

	private static String bytesHex(byte[] bytes) {
		StringBuilder sb = new StringBuilder();
		for (byte b : bytes) {
			sb.append(String.format("%02x", b));
		}
		return sb.toString();
	}

	private static String addrList(Set<Function> functions) {
		List<String> addrs = new ArrayList<>();
		Set<Function> sorted = new TreeSet<>(BY_ENTRY);
		sorted.addAll(functions);
		for (Function f : sorted) {
			addrs.add(quote(hex(f.getEntryPoint())));
		}
		return "[" + String.join(",", addrs) + "]";
	}

	private static String quote(String s) {
		StringBuilder sb = new StringBuilder("\"");
		for (char c : s.toCharArray()) {
			switch (c) {
				case '"' -> sb.append("\\\"");
				case '\\' -> sb.append("\\\\");
				case '\n' -> sb.append("\\n");
				case '\r' -> sb.append("\\r");
				case '\t' -> sb.append("\\t");
				default -> sb.append(c < 0x20 ? String.format("\\u%04x", (int) c) : String.valueOf(c));
			}
		}
		return sb.append('"').toString();
	}
}
