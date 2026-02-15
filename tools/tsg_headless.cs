using System;
using System.IO;
using System.Linq;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.Metadata;
using Mono.Cecil;

namespace TsgHeadless
{
    public enum Side
    {
        Client,
        Server,
        Unknown,
    }

    public enum Platform
    {
        Windows,
        Linux,
        Mac,
        Unknown,
    }

    public class AssemblyInfo : IDisposable
    {
        public byte[] FileRawBytes { get; }
        public AssemblyDefinition Assembly { get; }
        public Side Side { get; }
        public Platform Platform { get; }
        public Version AssemblyVersion { get; }
        public int ReleaseNumber { get; }

        private MemoryStream _asmStream;

        public AssemblyInfo(Stream stream)
        {
            if (stream == null) throw new ArgumentNullException(nameof(stream));
            using (var br = new BinaryReader(stream))
                FileRawBytes = br.ReadBytes((int)stream.Length);
            _asmStream = new MemoryStream(FileRawBytes);
            Assembly = AssemblyDefinition.ReadAssembly(_asmStream);

            switch (Assembly.Name.Name)
            {
                case "Terraria":
                    Side = Side.Client;
                    break;
                case "TerrariaServer":
                    Side = Side.Server;
                    break;
                default:
                    Side = Side.Unknown;
                    break;
            }

            switch (Assembly.MainModule.EntryPoint.DeclaringType.FullName)
            {
                case "Terraria.WindowsLaunch":
                    Platform = Platform.Windows;
                    break;
                case "Terraria.LinuxLaunch":
                    Platform = Platform.Linux;
                    break;
                case "Terraria.MacLaunch":
                    Platform = Platform.Mac;
                    break;
                default:
                    Platform = Platform.Unknown;
                    break;
            }

            AssemblyVersion = Assembly.Name.Version;

            ReleaseNumber = (int)Assembly.MainModule
                .Types.First(t => t.FullName == "Terraria.Main")
                .Fields.First(f => f.Name == "curRelease")
                .Constant;
        }

        public void Dispose()
        {
            Assembly?.Dispose();
            _asmStream?.Dispose();
        }
    }

    class Program
    {
        static int Main(string[] args)
        {
            if (args.Length < 1)
            {
                Console.WriteLine("Usage: tsg_headless.exe <assembly-path> [output-dir]");
                return 1;
            }

            var asmPath = args[0];
            if (!File.Exists(asmPath))
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine($"Invalid path: {asmPath}");
                Console.ResetColor();
                return 1;
            }

            var outputDir = args.Length > 1 ? args[1] : null;

            using (var asmInfo = new AssemblyInfo(File.OpenRead(asmPath)))
            {
                if (outputDir == null)
                    outputDir = $"{asmInfo.AssemblyVersion}-{asmInfo.ReleaseNumber}-{asmInfo.Platform}-{asmInfo.Side}";

                if (!Directory.Exists(outputDir))
                {
                    Directory.CreateDirectory(outputDir);
                }

                var referenceDirPath = Path.Combine(outputDir, "references");
                Directory.CreateDirectory(referenceDirPath);
                ExtractReferences(asmInfo, referenceDirPath);

                var decompiler = new WholeProjectDecompiler();
                decompiler.ProgressIndicator = null;

                var resolver = new UniversalAssemblyResolver("./", false, "");
                resolver.AddSearchDirectory(new DirectoryInfo(referenceDirPath).FullName);
                var dirPath = Path.GetDirectoryName(asmPath);
                if (!string.IsNullOrEmpty(dirPath))
                    resolver.AddSearchDirectory(dirPath);
                decompiler.AssemblyResolver = resolver;

                using (var ms = new MemoryStream(asmInfo.FileRawBytes))
                {
                    Console.WriteLine("Start decompiling...");
                    var peFile = new PEFile(asmInfo.Assembly.Name.Name, ms);
                    decompiler.DecompileProject(peFile, outputDir);

                    var csprojPath = Path.Combine(outputDir, $"{asmInfo.Assembly.Name.Name}.csproj");
                    if (File.Exists(csprojPath))
                        File.WriteAllText(csprojPath, PostProcessProjectFile(File.ReadAllText(csprojPath)));
                }
            }

            return 0;
        }

        static string PostProcessProjectFile(string csproj)
        {
            return csproj
                .Replace("<TargetFrameworkProfile>Client</TargetFrameworkProfile>", "")
                .Replace("<TargetFrameworkVersion>v4.0</TargetFrameworkVersion>", "<TargetFrameworkVersion>v4.5</TargetFrameworkVersion>")
                .Replace("<Reference Include=\"System.Core\">", "<Reference Include=\"System.Xml\" />\n    <Reference Include=\"System.Core\">");
        }

        static void ExtractReferences(AssemblyInfo asmInfo, string targetDir)
        {
            foreach (var r in asmInfo.Assembly.MainModule.Resources
                .Where(r => r.ResourceType == Mono.Cecil.ResourceType.Embedded && r.Name.EndsWith(".dll"))
                .Select(r => r as EmbeddedResource))
            {
                if (r == null) continue;
                var asmName = AssemblyDefinition.ReadAssembly(r.GetResourceStream()).Name.Name;
                File.WriteAllBytes(Path.Combine(targetDir, $"{asmName}.dll"), r.GetResourceData());
            }
        }
    }
}
