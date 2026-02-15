using System;
using System.IO;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.Metadata;

class DecompileTool
{
    static int Main(string[] args)
    {
        if (args.Length < 2)
        {
            Console.WriteLine("Usage: decompile_tml <assembly> <outdir> [refdir...]");
            return 1;
        }

        var asmPath = args[0];
        var outDir = args[1];
        if (!File.Exists(asmPath))
        {
            Console.WriteLine("Assembly not found: " + asmPath);
            return 1;
        }

        Directory.CreateDirectory(outDir);

        var resolver = new UniversalAssemblyResolver("./", false, "");
        var asmDir = Path.GetDirectoryName(Path.GetFullPath(asmPath));
        if (!string.IsNullOrEmpty(asmDir))
            resolver.AddSearchDirectory(asmDir);
        for (int i = 2; i < args.Length; i++)
        {
            if (Directory.Exists(args[i]))
                resolver.AddSearchDirectory(args[i]);
        }

        var decompiler = new WholeProjectDecompiler();
        decompiler.AssemblyResolver = resolver;

        Console.WriteLine("Decompiling: " + asmPath);
        Console.WriteLine("Output: " + outDir);
        var pe = new PEFile(asmPath);
        decompiler.DecompileProject(pe, outDir);
        Console.WriteLine("Done.");
        return 0;
    }
}
